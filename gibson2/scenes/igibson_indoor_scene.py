import time
import gibson2
import logging
import numpy as np
from gibson2.objects.articulated_object import URDFObject
from gibson2.utils.utils import rotate_vector_3d, rotate_vector_2d
import pybullet as p
import os
import xml.etree.ElementTree as ET
from gibson2.scenes.gibson_indoor_scene import StaticIndoorScene
import random
import json
from gibson2.utils.assets_utils import get_ig_avg_category_specs, get_ig_scene_path, get_ig_model_path, get_ig_category_path, get_ig_category_ids, get_cubicasa_scene_path, get_3dfront_scene_path
from gibson2.external.pybullet_tools.utils import euler_from_quat
from PIL import Image

SCENE_SOURCE = ['IG', 'CUBICASA', 'THREEDFRONT']


class InteractiveIndoorScene(StaticIndoorScene):
    """
    Create an interactive scene defined with iGibson Scene Description Format (iGSDF).
    iGSDF is an extension of URDF that we use to define an interactive scene.
    It has support for URDF scaling, URDF nesting and randomization.
    InteractiveIndoorScene inherits from StaticIndoorScene the functionalities to compute shortest path and other
    navigation functionalities.
    """

    def __init__(self,
                 scene_id,
                 urdf_file=None,
                 trav_map_resolution=0.1,
                 trav_map_erosion=2,
                 trav_map_type='with_obj',
                 build_graph=True,
                 num_waypoints=10,
                 waypoint_resolution=0.2,
                 pybullet_load_texture=False,
                 texture_randomization=False,
                 link_collision_tolerance=0.03,
                 object_randomization=False,
                 object_randomization_idx=None,
                 should_open_all_doors=False,
                 load_object_categories=None,
                 not_load_object_categories=None,
                 load_room_types=None,
                 load_room_instances=None,
                 seg_map_resolution=0.1,
                 scene_source="IG",
                 ):
        """
        :param scene_id: Scene id
        :param urdf_file: Optional specification of which urdf file to load
        :param trav_map_resolution: traversability map resolution
        :param trav_map_erosion: erosion radius of traversability areas, should be robot footprint radius
        :param trav_map_type: type of traversability map, with_obj | no_obj
        :param build_graph: build connectivity graph
        :param num_waypoints: number of way points returned
        :param waypoint_resolution: resolution of adjacent way points
        :param pybullet_load_texture: whether to load texture into pybullet. This is for debugging purpose only and does not affect robot's observations
        :param texture_randomization: whether to randomize material/texture
        :param link_collision_tolerance: tolerance of the percentage of links that cannot be fully extended after object randomization
        :param object_randomization: whether to randomize object
        :param object_randomization_idx: index of a pre-computed object randomization model that guarantees good scene quality
        :param should_open_all_doors: whether to open all doors after episode reset (usually required for navigation tasks)
        :param load_object_categories: only load these object categories into the scene (a list of str)
        :param not_load_object_categories: do not load these object categories into the scene (a list of str)
        :param load_room_types: only load objects in these room types into the scene (a list of str)
        :param load_room_instances: only load objects in these room instances into the scene (a list of str)
        :param seg_map_resolution: room segmentation map resolution
        :param scene_source: source of scene data; among IG, CUBICASA, THREEDFRONT
        """

        super(InteractiveIndoorScene, self).__init__(
            scene_id,
            trav_map_resolution,
            trav_map_erosion,
            trav_map_type,
            build_graph,
            num_waypoints,
            waypoint_resolution,
            pybullet_load_texture,
        )
        self.texture_randomization = texture_randomization
        self.object_randomization = object_randomization
        self.should_open_all_doors = should_open_all_doors
        if urdf_file is None:
            if object_randomization:
                if object_randomization_idx is None:
                    fname = scene_id
                else:
                    fname = '{}_random_{}'.format(scene_id,
                                                  object_randomization_idx)
            else:
                fname = '{}_best'.format(scene_id)
        else:
            fname = urdf_file
        if scene_source not in SCENE_SOURCE:
            raise ValueError(
                'Unsupported scene source: {}'.format(scene_source))
        if scene_source == "IG":
            scene_dir = get_ig_scene_path(scene_id)
        elif scene_source == "CUBICASA":
            scene_dir = get_cubicasa_scene_path(scene_id)
        else:
            scene_dir = get_3dfront_scene_path(scene_id)
        self.scene_source = scene_source
        self.scene_dir = scene_dir
        self.scene_file = os.path.join(
            scene_dir, "urdf", "{}.urdf".format(fname))
        self.scene_tree = ET.parse(self.scene_file)
        self.random_groups = {}
        self.objects_by_category = {}
        self.objects_by_name = {}
        self.objects_by_id = {}
        self.objects_by_room = {}
        self.objects_by_state = {}
        self.category_ids = get_ig_category_ids()

        # Current time string to use to save the temporal urdfs
        timestr = time.strftime("%Y%m%d-%H%M%S")
        # Create the subfolder
        self.scene_instance_folder = os.path.join(
            gibson2.ig_dataset_path, "scene_instances",
            '{}_{}_{}'.format(timestr, random.getrandbits(64), os.getpid()))
        os.makedirs(self.scene_instance_folder, exist_ok=True)

        # Load room semantic and instance segmentation map
        self.load_room_sem_ins_seg_map(seg_map_resolution)

        # Decide which room(s) and object categories to load
        self.filter_rooms_and_object_categories(
            load_object_categories, not_load_object_categories,
            load_room_types, load_room_instances)

        # Load average object density if exists
        self.avg_obj_dims = get_ig_avg_category_specs()

        # load overlapping bboxes in scene annotation
        self.overlapped_bboxes = self.load_overlapped_bboxes()

        # percentage of objects allowed that CANNOT extend their joints by >66%
        self.link_collision_tolerance = link_collision_tolerance

        # Parse all the special link entries in the root URDF that defines the scene
        for link in self.scene_tree.findall('link'):
            if 'category' in link.attrib:
                # Extract category and model from the link entry
                category = link.attrib["category"]
                model = link.attrib["model"]

                # An object can in multiple rooms, seperated by commas,
                # or None if the object is one of the walls, floors or ceilings
                in_rooms = link.attrib.get('room', None)
                if in_rooms is not None:
                    in_rooms = in_rooms.split(',')

                # Do not load these object categories (potentially building structures as well)
                if self.not_load_object_categories is not None and \
                        category in self.not_load_object_categories:
                    continue

                # Find the urdf file that defines this object
                if category in ["walls", "floors", "ceilings"]:
                    model_path = self.scene_dir
                    filename = os.path.join(
                        model_path, "urdf", model + "_" + category + ".urdf")

                # For other objects
                else:
                    # This object does not belong to one of the selected object categories, skip
                    if self.load_object_categories is not None and \
                            category not in self.load_object_categories:
                        continue
                    # This object is not located in one of the selected rooms, skip
                    if self.load_room_instances is not None and \
                            len(set(self.load_room_instances) & set(in_rooms)) == 0:
                        continue

                    category_path = get_ig_category_path(category)
                    assert len(os.listdir(category_path)) != 0, \
                        "There are no models in category folder {}".format(
                            category_path)

                    if model == 'random':
                        # Using random group to assign the same model to a group of objects
                        # E.g. we want to use the same model for a group of chairs around the same dining table
                        if "random_group" in link.attrib:
                            # random_group is a unique integer within the category
                            random_group = link.attrib["random_group"]
                            random_group_key = (category, random_group)

                            # if the model of this random group has already been selected
                            # use that model.
                            if random_group_key in self.random_groups:
                                model = self.random_groups[random_group_key]

                            # otherwise, this is the first instance of this random group
                            # select a random model and cache it
                            else:
                                model = random.choice(
                                    os.listdir(category_path))
                                self.random_groups[random_group_key] = model
                        else:
                            # Using a random instance
                            model = random.choice(os.listdir(category_path))
                    else:
                        model = link.attrib['model']

                    model_path = get_ig_model_path(category, model)
                    filename = os.path.join(model_path, model + ".urdf")

                if "bounding_box" in link.keys() and "scale" in link.keys():
                    logging.error(
                        "You cannot define both scale and bounding box size to embed a URDF")
                    exit(-1)

                bounding_box = None
                scale = None
                if "bounding_box" in link.keys():
                    bounding_box = np.array(
                        [float(val) for val in link.attrib["bounding_box"].split(" ")])
                elif "scale" in link.keys():
                    scale = np.array([float(val)
                                      for val in link.attrib["scale"].split(" ")])
                else:
                    scale = np.array([1., 1., 1.])

                object_name = link.attrib['name']

                # The joint location is given wrt the bounding box center but we need it wrt to the base_link frame
                joint_connecting_embedded_link = \
                    [joint for joint in self.scene_tree.findall("joint")
                     if joint.find("child").attrib["link"]
                     == object_name][0]

                obj = URDFObject(
                    filename,
                    name=object_name,
                    category=category,
                    model_path=model_path,
                    bounding_box=bounding_box,
                    scale=scale,
                    connecting_joint=joint_connecting_embedded_link,
                    avg_obj_dims=self.avg_obj_dims.get(category),
                    in_rooms=in_rooms,
                    texture_randomization=texture_randomization,
                    overwrite_inertial=True,
                    scene_instance_folder=self.scene_instance_folder)

                self.add_object(obj)

            elif link.attrib["name"] != "world":
                logging.error(
                    "iGSDF should only contain links that represent embedded URDF objects")

    def get_objects(self):
        return list(self.objects_by_name.values())

    def get_objects_with_state(self, state):
        # We overload this method to provide a faster implementation.
        return list(self.objects_by_state[state]) if state in self.objects_by_state else []

    def filter_rooms_and_object_categories(self,
                                           load_object_categories,
                                           not_load_object_categories,
                                           load_room_types,
                                           load_room_instances):
        """
        Handle partial scene loading based on object categories, room types or room instances

        :param load_object_categories: only load these object categories into the scene (a list of str)
        :param not_load_object_categories: do not load these object categories into the scene (a list of str)
        :param load_room_types: only load objects in these room types into the scene (a list of str)
        :param load_room_instances: only load objects in these room instances into the scene (a list of str)
        """

        if isinstance(load_object_categories, str):
            load_object_categories = [load_object_categories]
        self.load_object_categories = load_object_categories

        if isinstance(not_load_object_categories, str):
            not_load_object_categories = [not_load_object_categories]
        self.not_load_object_categories = not_load_object_categories

        if load_room_instances is not None:
            if isinstance(load_room_instances, str):
                load_room_instances = [load_room_instances]
            load_room_instances_filtered = []
            for room_instance in load_room_instances:
                if room_instance in self.room_ins_name_to_ins_id:
                    load_room_instances_filtered.append(room_instance)
                else:
                    logging.warning(
                        'room_instance [{}] does not exist.'.format(room_instance))
            self.load_room_instances = load_room_instances_filtered
        elif load_room_types is not None:
            if isinstance(load_room_types, str):
                load_room_types = [load_room_types]
            load_room_instances_filtered = []
            for room_type in load_room_types:
                if room_type in self.room_sem_name_to_ins_name:
                    load_room_instances_filtered.extend(
                        self.room_sem_name_to_ins_name[room_type])
                else:
                    logging.warning(
                        'room_type [{}] does not exist.'.format(room_type))
            self.load_room_instances = load_room_instances_filtered
        else:
            self.load_room_instances = None

    def load_room_sem_ins_seg_map(self, seg_map_resolution):
        """
        Load room segmentation map

        :param seg_map_resolution: room segmentation map resolution
        """
        layout_dir = os.path.join(self.scene_dir, "layout")
        room_seg_imgs = os.path.join(layout_dir, 'floor_insseg_0.png')
        img_ins = Image.open(room_seg_imgs)
        room_seg_imgs = os.path.join(layout_dir, 'floor_semseg_0.png')
        img_sem = Image.open(room_seg_imgs)
        height, width = img_ins.size
        assert height == width, 'room seg map is not a square'
        assert img_ins.size == img_sem.size, 'semantic and instance seg maps have different sizes'
        self.seg_map_default_resolution = 0.01
        self.seg_map_resolution = seg_map_resolution
        self.seg_map_size = int(height *
                                self.seg_map_default_resolution /
                                self.seg_map_resolution)
        img_ins = np.array(img_ins.resize(
            (self.seg_map_size, self.seg_map_size), Image.NEAREST))
        img_sem = np.array(img_sem.resize(
            (self.seg_map_size, self.seg_map_size), Image.NEAREST))

        room_categories = os.path.join(
            gibson2.ig_dataset_path, 'metadata', 'room_categories.txt')
        with open(room_categories, 'r') as fp:
            room_cats = [line.rstrip() for line in fp.readlines()]

        sem_id_to_ins_id = {}
        unique_ins_ids = np.unique(img_ins)
        unique_ins_ids = np.delete(unique_ins_ids, 0)
        for ins_id in unique_ins_ids:
            # find one pixel for each ins id
            x, y = np.where(img_ins == ins_id)
            # retrieve the correspounding sem id
            sem_id = img_sem[x[0], y[0]]
            if sem_id not in sem_id_to_ins_id:
                sem_id_to_ins_id[sem_id] = []
            sem_id_to_ins_id[sem_id].append(ins_id)

        room_sem_name_to_sem_id = {}
        room_ins_name_to_ins_id = {}
        room_sem_name_to_ins_name = {}
        for sem_id, ins_ids in sem_id_to_ins_id.items():
            sem_name = room_cats[sem_id - 1]
            room_sem_name_to_sem_id[sem_name] = sem_id
            for i, ins_id in enumerate(ins_ids):
                # valid class start from 1
                ins_name = "{}_{}".format(sem_name, i)
                room_ins_name_to_ins_id[ins_name] = ins_id
                if sem_name not in room_sem_name_to_ins_name:
                    room_sem_name_to_ins_name[sem_name] = []
                room_sem_name_to_ins_name[sem_name].append(ins_name)

        self.room_sem_name_to_sem_id = room_sem_name_to_sem_id
        self.room_sem_id_to_sem_name = {
            value: key for key, value in room_sem_name_to_sem_id.items()}
        self.room_ins_name_to_ins_id = room_ins_name_to_ins_id
        self.room_ins_id_to_ins_name = {
            value: key for key, value in room_ins_name_to_ins_id.items()}
        self.room_sem_name_to_ins_name = room_sem_name_to_ins_name
        self.room_ins_map = img_ins
        self.room_sem_map = img_sem

    def load_overlapped_bboxes(self):
        """
        Load overlapped bounding boxes in scene definition.
        E.g. a dining table usually has overlaps with the surrounding dining chairs
        """
        bbox_overlap_file = os.path.join(
            self.scene_dir, 'misc', 'bbox_overlap.json')
        if os.path.isfile(bbox_overlap_file):
            with open(bbox_overlap_file) as f:
                return json.load(f)
        else:
            return []

    def _add_object(self, obj):
        """
        Adds an object to the scene

        :param obj: Object instance to add to scene.
        """
        if hasattr(obj, "category"):
            category = obj.category
        else:
            category = 'object'

        if hasattr(obj, "name"):
            object_name = obj.name
        else:
            object_name = '{}_{}'.format(
                category, len(self.objects_by_category.get(category, [])))

        if object_name in self.objects_by_name.keys():
            logging.error(
                "Object names need to be unique! Existing name " + object_name)
            exit(-1)

        # Add object to database
        self.objects_by_name[object_name] = obj
        if category not in self.objects_by_category.keys():
            self.objects_by_category[category] = []
        self.objects_by_category[category].append(obj)

        if hasattr(obj, "states"):
            for state in obj.states:
                if state not in self.objects_by_state:
                    self.objects_by_state[state] = []

                self.objects_by_state[state].append(obj)

        if hasattr(obj, "in_rooms"):
            in_rooms = obj.in_rooms
            if in_rooms is not None:
                for in_room in in_rooms:
                    if in_room not in self.objects_by_room.keys():
                        self.objects_by_room[in_room] = []
                    self.objects_by_room[in_room].append(obj)

    def randomize_texture(self):
        """
        Randomize texture/material for all objects in the scene
        """
        if not self.texture_randomization:
            logging.warning(
                'calling randomize_texture while texture_randomization is False during initialization.')
            return
        for int_object in self.objects_by_name:
            obj = self.objects_by_name[int_object]
            obj.randomize_texture()

    def check_collision(self, body_a, body_b=None, link_a=None, fixed_body_ids=None):
        """
        Helper function to check for collision for scene quality
        """
        if body_b is None:
            assert link_a is not None
            pts = p.getContactPoints(bodyA=body_a, linkIndexA=link_a)
        else:
            assert body_b is not None
            pts = p.getContactPoints(bodyA=body_a, bodyB=body_b)

        # contactDistance < 0 means actual penetration
        pts = [elem for elem in pts if elem[8] < 0.0]

        # only count collision with fixed body ids if provided
        if fixed_body_ids is not None:
            pts = [elem for elem in pts if elem[2] in fixed_body_ids]

        return len(pts) > 0

    def check_scene_quality(self, body_ids, fixed_body_ids):
        """
        Helper function to check for scene quality.
        1) Objects should have no collision with each other.
        2) Fixed, articulated objects that cannot fully extend their joints should be less than self.link_collision_tolerance

        :param body_ids: body ids of all scene objects
        :param fixed_body_ids: body ids of all fixed scene objects
        :return: whether scene passes quality check
        """
        quality_check = True

        body_body_collision = []
        body_link_collision = []

        # build mapping from body_id to object name for debugging
        body_id_to_name = {}
        for name in self.objects_by_name:
            for body_id in self.objects_by_name[name].body_ids:
                body_id_to_name[body_id] = name
        self.body_id_to_name = body_id_to_name

        # collect body ids for overlapped bboxes (e.g. tables and chairs,
        # sofas and coffee tables)
        overlapped_body_ids = []
        for obj1_name, obj2_name in self.overlapped_bboxes:
            if obj1_name not in self.objects_by_name or obj2_name not in self.objects_by_name:
                # This could happen if only part of the scene is loaded (e.g. only a subset of rooms)
                continue
            for obj1_body_id in self.objects_by_name[obj1_name].body_ids:
                for obj2_body_id in self.objects_by_name[obj2_name].body_ids:
                    overlapped_body_ids.append((obj1_body_id, obj2_body_id))

        # cache pybullet initial state
        state_id = p.saveState()

        # check if these overlapping bboxes have collision
        p.stepSimulation()
        for body_a, body_b in overlapped_body_ids:
            has_collision = self.check_collision(body_a=body_a, body_b=body_b)
            quality_check = quality_check and (not has_collision)
            if has_collision:
                body_body_collision.append((body_a, body_b))

        # check if fixed, articulated objects can extend their joints
        # without collision with other fixed objects
        joint_collision_allowed = int(
            len(body_ids) * self.link_collision_tolerance)
        joint_collision_so_far = 0
        for body_id in fixed_body_ids:
            joint_quality = True
            for joint_id in range(p.getNumJoints(body_id)):
                j_low, j_high = p.getJointInfo(body_id, joint_id)[8:10]
                j_type = p.getJointInfo(body_id, joint_id)[2]
                if j_type not in [p.JOINT_REVOLUTE, p.JOINT_PRISMATIC]:
                    continue
                # this is the continuous joint (e.g. wheels for office chairs)
                if j_low >= j_high:
                    continue

                # usually j_low and j_high includes j_default = 0.0
                # if not, set j_default to be j_low
                j_default = 0.0
                if not (j_low <= j_default <= j_high):
                    j_default = j_low

                # check three joint positions, 0%, 33% and 66%
                j_range = j_high - j_low
                j_low_perc = j_range * 0.33 + j_low
                j_high_perc = j_range * 0.66 + j_low

                # check if j_default has collision
                p.restoreState(state_id)
                p.resetJointState(body_id, joint_id, j_default)
                p.stepSimulation()
                has_collision = self.check_collision(
                    body_a=body_id, link_a=joint_id, fixed_body_ids=fixed_body_ids)
                joint_quality = joint_quality and (not has_collision)

                # check if j_low_perc has collision
                p.restoreState(state_id)
                p.resetJointState(body_id, joint_id, j_low_perc)
                p.stepSimulation()
                has_collision = self.check_collision(
                    body_a=body_id, link_a=joint_id, fixed_body_ids=fixed_body_ids)
                joint_quality = joint_quality and (not has_collision)

                # check if j_high_perc has collision
                p.restoreState(state_id)
                p.resetJointState(body_id, joint_id, j_high_perc)
                p.stepSimulation()
                has_collision = self.check_collision(
                    body_a=body_id, link_a=joint_id, fixed_body_ids=fixed_body_ids)
                joint_quality = joint_quality and (not has_collision)

            if not joint_quality:
                joint_collision_so_far += 1
                body_link_collision.append(body_id)

        quality_check = quality_check and (
            joint_collision_so_far <= joint_collision_allowed)

        # restore state to the initial state before testing collision
        p.restoreState(state_id)

        self.quality_check = quality_check

        self.body_collision_set = set()
        for body_a, body_b in body_body_collision:
            logging.warning('scene quality check: {} and {} has collision.'.format(
                body_id_to_name[body_a],
                body_id_to_name[body_b],
            ))
            self.body_collision_set.add(body_id_to_name[body_a])
            self.body_collision_set.add(body_id_to_name[body_b])

        self.link_collision_set = set()
        for body_id in body_link_collision:
            logging.warning('scene quality check: {} has joint that cannot extend for >66%.'.format(
                body_id_to_name[body_id],
            ))
            self.link_collision_set.add(body_id_to_name[body_id])

        return self.quality_check

    def _set_first_n_objects(self, first_n_objects):
        """
        Only load the first N objects. Hidden API for debugging purposes.

        :param first_n_objects: only load the first N objects (integer)
        """
        raise ValueError(
            "The _set_first_n_object function is now deprecated due to "
            "incompatibility with recent object state features. Please "
            "use the load_object_categories method for limiting the "
            "objects to be loaded from the scene.")

    def _set_obj_names_to_load(self, obj_name_list):
        """
        Only load in objects with the given string names. Hidden API as is only
        used internally in the VR benchmark. This function automatically
        adds walls, floors and ceilings to the room.

        :param obj_name_list: list of string object names. These names must
            all be in the scene URDF file.
        """
        raise ValueError(
            "The _set_obj_names_to_load function is now deprecated due "
            "to incompatibility with recent object state features. Please "
            "use the load_object_categories method for limiting the "
            "objects to be loaded from the scene.")

    def open_one_obj(self, body_id, mode='random'):
        """
        Attempt to open one object without collision

        :param body_id: body id of the object
        :param mode: opening mode (zero, max, or random)
        """
        body_joint_pairs = []
        for joint_id in range(p.getNumJoints(body_id)):
            # cache current physics state
            state_id = p.saveState()

            j_low, j_high = p.getJointInfo(body_id, joint_id)[8:10]
            j_type = p.getJointInfo(body_id, joint_id)[2]
            parent_idx = p.getJointInfo(body_id, joint_id)[-1]
            if j_type not in [p.JOINT_REVOLUTE, p.JOINT_PRISMATIC]:
                p.removeState(state_id)
                continue
            # this is the continuous joint
            if j_low >= j_high:
                p.removeState(state_id)
                continue
            # this is the 2nd degree joint, ignore for now
            if parent_idx != 0:
                p.removeState(state_id)
                continue

            if mode == 'max':
                # try to set the joint to the maxr value until no collision
                # step_size is 5cm for prismatic joint and 5 degrees for revolute joint
                step_size = np.pi / 36.0 if j_type == p.JOINT_REVOLUTE else 0.05
                for j_pos in np.arange(0.0, j_high + step_size, step=step_size):
                    p.resetJointState(
                        body_id, joint_id, j_high - j_pos)
                    p.stepSimulation()
                    has_collision = self.check_collision(
                        body_a=body_id, link_a=joint_id)
                    p.restoreState(state_id)
                    if not has_collision:
                        p.resetJointState(body_id, joint_id, j_high - j_pos)
                        break

            elif mode == 'random':
                # try to set the joint to a random value until no collision
                reset_success = False
                # make 10 attemps
                for _ in range(10):
                    j_pos = np.random.uniform(j_low, j_high)
                    p.resetJointState(
                        body_id, joint_id, j_pos)
                    p.stepSimulation()
                    has_collision = self.check_collision(
                        body_a=body_id, link_a=joint_id)
                    p.restoreState(state_id)
                    if not has_collision:
                        p.resetJointState(body_id, joint_id, j_pos)
                        reset_success = True
                        break

                # if none of the random values work, set it to 0.0 by default
                if not reset_success:
                    p.resetJointState(body_id, joint_id, 0.0)
            elif mode == 'zero':
                p.resetJointState(body_id, joint_id, 0.0)
            else:
                assert False

            body_joint_pairs.append((body_id, joint_id))
            # Remove cached state to avoid memory leak.
            p.removeState(state_id)

        return body_joint_pairs

    def open_all_objs_by_category(self, category, mode='random', prob=1.0):
        """
        Attempt to open all objects of a certain category without collision

        :param category: object category (str)
        :param mode: opening mode (zero, max, or random)
        :param prob: opening probability
        """
        body_joint_pairs = []
        if category not in self.objects_by_category:
            return body_joint_pairs
        for obj in self.objects_by_category[category]:
            # open probability
            if np.random.random() > prob:
                continue
            for body_id in obj.body_ids:
                body_joint_pairs += self.open_one_obj(body_id, mode=mode)
        return body_joint_pairs

    def open_all_objs_by_categories(self, categories, mode='random', prob=1.0):
        """
        Attempt to open all objects of a number of categories without collision

        :param categories: object categories (a list of str)
        :param mode: opening mode (zero, max, or random)
        :param prob: opening probability
        """
        body_joint_pairs = []
        for category in categories:
            body_joint_pairs += self.open_all_objs_by_category(
                category, mode=mode, prob=prob)
        return body_joint_pairs

    def open_all_doors(self):
        """
        Attempt to open all doors to maximum values without collision
        """
        return self.open_all_objs_by_category('door', mode='max')

    def _load(self):
        """
        Load all scene objects into pybullet
        """
        # Load all the objects
        body_ids = []
        fixed_body_ids = []
        visual_mesh_to_material = []
        for int_object in self.objects_by_name:
            obj = self.objects_by_name[int_object]
            new_ids = obj.load()
            for id in new_ids:
                self.objects_by_id[id] = obj
            body_ids += new_ids
            visual_mesh_to_material += obj.visual_mesh_to_material
            fixed_body_ids += [body_id for body_id, is_fixed
                               in zip(obj.body_ids, obj.is_fixed)
                               if is_fixed]

        # disable collision between the fixed links of the fixed objects
        for i in range(len(fixed_body_ids)):
            for j in range(i + 1, len(fixed_body_ids)):
                # link_id = 0 is the base link that is connected to the world
                # by a fixed link
                p.setCollisionFilterPair(
                    fixed_body_ids[i],
                    fixed_body_ids[j],
                    0, 0, enableCollision=0)

        # Load the traversability map
        maps_path = os.path.join(self.scene_dir, "layout")
        if self.build_graph:
            self.load_trav_map(maps_path)

        self.visual_mesh_to_material = visual_mesh_to_material
        self.check_scene_quality(body_ids, fixed_body_ids)

        # force wake up each body once
        self.force_wakeup_scene_objects()
        return body_ids

    def force_wakeup_scene_objects(self):
        """
        Force wakeup sleeping objects
        """
        for obj_name in self.objects_by_name:
            self.objects_by_name[obj_name].force_wakeup()

    def reset_scene_objects(self):
        """
        Reset the pose and joint configuration of all scene objects.
        Also open all doors if self.should_open_all_doors is True
        """
        for obj_name in self.objects_by_name:
            self.objects_by_name[obj_name].reset()

        if self.should_open_all_doors:
            self.force_wakeup_scene_objects()
            self.open_all_doors()

    def get_num_objects(self):
        """
        Get the number of objects

        :return: number of objects
        """
        return len(self.objects_by_name)

    def get_random_point_by_room_type(self, room_type):
        """
        Sample a random point by room type

        :param room_type: room type (e.g. bathroom)
        :return: floor (always 0), a randomly sampled point in [x, y, z]
        """
        if room_type not in self.room_sem_name_to_sem_id:
            logging.warning('room_type [{}] does not exist.'.format(room_type))
            return None, None

        sem_id = self.room_sem_name_to_sem_id[room_type]
        valid_idx = np.array(np.where(self.room_sem_map == sem_id))
        random_point_map = valid_idx[:, np.random.randint(valid_idx.shape[1])]

        x, y = self.seg_map_to_world(random_point_map)
        # assume only 1 floor
        floor = 0
        z = self.floor_heights[floor]
        return floor, np.array([x, y, z])

    def get_random_point_by_room_instance(self, room_instance):
        """
        Sample a random point by room instance

        :param room_instance: room instance (e.g. bathroom_1)
        :return: floor (always 0), a randomly sampled point in [x, y, z]
        """
        if room_instance not in self.room_ins_name_to_ins_id:
            logging.warning(
                'room_instance [{}] does not exist.'.format(room_instance))
            return None, None

        ins_id = self.room_ins_name_to_ins_id[room_instance]
        valid_idx = np.array(np.where(self.room_ins_map == ins_id))
        random_point_map = valid_idx[:, np.random.randint(valid_idx.shape[1])]

        x, y = self.seg_map_to_world(random_point_map)
        # assume only 1 floor
        floor = 0
        z = self.floor_heights[floor]
        return floor, np.array([x, y, z])

    def seg_map_to_world(self, xy):
        """
        Transforms a 2D point in map reference frame into world (simulator) reference frame

        :param xy: 2D location in seg map reference frame (image)
        :return: 2D location in world reference frame (metric)
        """
        axis = 0 if len(xy.shape) == 1 else 1
        return np.flip((xy - self.seg_map_size / 2.0) * self.seg_map_resolution, axis=axis)

    def world_to_seg_map(self, xy):
        """
        Transforms a 2D point in world (simulator) reference frame into map reference frame

        :param xy: 2D location in world reference frame (metric)
        :return: 2D location in seg map reference frame (image)
        """
        return np.flip((xy / self.seg_map_resolution + self.seg_map_size / 2.0)).astype(np.int)

    def get_room_type_by_point(self, xy):
        """
        Return the room type given a point

        :param xy: 2D location in world reference frame (metric)
        :return: room type that this point is in or None, if this point is not on the room segmentation map
        """
        x, y = self.world_to_seg_map(xy)
        sem_id = self.room_sem_map[x, y]
        # room boundary
        if sem_id == 0:
            return None
        else:
            return self.room_sem_id_to_sem_name[sem_id]

    def get_room_instance_by_point(self, xy):
        """
        Return the room instance given a point

        :param xy: 2D location in world reference frame (metric)
        :return: room instance that this point is in or None, if this point is not on the room segmentation map
        """

        x, y = self.world_to_seg_map(xy)
        ins_id = self.room_ins_map[x, y]
        # room boundary
        if ins_id == 0:
            return None
        else:
            return self.room_ins_id_to_ins_name[ins_id]

    def get_body_ids(self):
        """
        Return the body ids of all scene objects

        :return: body ids
        """
        ids = []
        for obj_name in self.objects_by_name:
            if self.objects_by_name[obj_name].body_id is not None:
                ids.extend(self.objects_by_name[obj_name].body_id)
        return ids

    def save_modified_urdf(self, urdf_name):
        """
        Saves a modified URDF file in the scene urdf directory having all objects added to the scene.

        :param urdf_name: Name of urdf file to save (without .urdf)
        """
        TEMPLATE = """
        <link bounding_box="{bounding_box}" category="{category}" model="{model}" name="{name}" room="{room}"/>
        <joint name="j_{name}" type="floating">
            <origin rpy="{rpy}" xyz="{xyz}"/>
            <child link="{name}"/>
            <parent link="world"/>
        </joint>"""
        with open(self.scene_file, 'r') as f:
            urdf_string = f.read()
        add_string = ''
        for name in self.objects_by_name:
            if name in urdf_string:
                continue
            obj = self.objects_by_name[name]
            if not hasattr(obj, 'in_rooms') or obj.in_rooms is None:
                continue
            category = obj.category
            model = name.split('|')[1]
            room = obj.in_rooms[0]
            bounding_box = ' '.join([str(b) for b in obj.bounding_box])

            # Convert from center of mass to base link position
            body_id = obj.body_ids[obj.main_body]
            dynamics_info = p.getDynamicsInfo(body_id, -1)
            inertial_pos = dynamics_info[3]
            inertial_orn = dynamics_info[4]

            pos, orn = obj.get_position_orientation()
            inv_inertial_pos, inv_inertial_orn =\
                p.invertTransform(inertial_pos, inertial_orn)
            base_link_position, base_link_orientation = p.multiplyTransforms(
                pos, orn, inv_inertial_pos, inv_inertial_orn)

            # Convert to XYZ position for URDF
            euler = euler_from_quat(obj.get_orientation())
            roll, pitch, yaw = euler
            offset = rotate_vector_3d(
                obj.scaled_bbxc_in_blf, roll, pitch, yaw, False)
            bbox_pos = base_link_position - offset

            xyz = ' '.join([str(p) for p in bbox_pos])
            rpy = ' '.join([str(e) for e in euler])
            new_string = TEMPLATE.format(bounding_box=bounding_box,
                                         category=category,
                                         model=model,
                                         name=name,
                                         room=room,
                                         rpy=rpy,
                                         xyz=xyz)
            add_string += new_string
        add_string += '\n</robot>'
        urdf_string = urdf_string.replace('</robot>', add_string)
        path_to_urdf = os.path.join(self.scene_dir, 'urdf', urdf_name+'.urdf')
        with open(path_to_urdf, 'w') as f:
            f.write(urdf_string)
