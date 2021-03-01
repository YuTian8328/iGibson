""" VR saving/replay demo.

This demo saves the actions of certain objects as well as states. Either can
be used to playback later in the replay demo.

In this demo, we save some "mock" VR actions that are already saved by default,
but can be saved separately as actions to demonstrate the action-saving system.
During replay, we use a combination of these actions and saved values to get data
that can be used to control the physics simulation without setting every object's
transform each frame.

Usage:
python vr_actions_sr.py --mode=[save/replay]

This demo saves to vr_logs/vr_actions_sr.h5
Run this demo (and also change the filename) if you would like to save your own data."""

import argparse
import numpy as np
import os
import pybullet as p
import pybullet_data
import time

import gibson2
from gibson2.render.mesh_renderer.mesh_renderer_cpu import MeshRendererSettings
from gibson2.render.mesh_renderer.mesh_renderer_vr import VrSettings
from gibson2.scenes.igibson_indoor_scene import InteractiveIndoorScene
from gibson2.objects.object_base import Object
from gibson2.objects.articulated_object import ArticulatedObject
from gibson2.objects.vr_objects import VrAgent
from gibson2.objects.visual_marker import VisualMarker
from gibson2.objects.ycb_object import YCBObject
from gibson2.simulator import Simulator
from gibson2.utils.vr_logging import VRLogReader, VRLogWriter
from gibson2 import assets_path

# Number of frames to save
FRAMES_TO_SAVE = 2000
# Set to false to load entire Rs_int scene
LOAD_PARTIAL = True
# Set to true to print PyBullet data - can be used to check whether replay was identical to saving
PRINT_PB = True
# Set to true to print VR data
PRINT_VR_DATA = False

def run_action_sr(mode):
    """
    Runs action save/replay. Mode can either be save or replay.
    """
    assert mode in ['save', 'replay']
    is_save = (mode == 'save')

    # HDR files for PBR rendering
    hdr_texture = os.path.join(
        gibson2.ig_dataset_path, 'scenes', 'background', 'probe_02.hdr')
    hdr_texture2 = os.path.join(
        gibson2.ig_dataset_path, 'scenes', 'background', 'probe_03.hdr')
    light_modulation_map_filename = os.path.join(
        gibson2.ig_dataset_path, 'scenes', 'Rs_int', 'layout', 'floor_lighttype_0.png')
    background_texture = os.path.join(
        gibson2.ig_dataset_path, 'scenes', 'background', 'urban_street_01.jpg')

    # VR rendering settings
    vr_rendering_settings = MeshRendererSettings(optimized=True,
                                                fullscreen=False,
                                                env_texture_filename=hdr_texture,
                                                env_texture_filename2=hdr_texture2,
                                                env_texture_filename3=background_texture,
                                                light_modulation_map_filename=light_modulation_map_filename,
                                                enable_shadow=True, 
                                                enable_pbr=True,
                                                msaa=True,
                                                light_dimming_factor=1.0)
    # VR system settings
    # Change use_vr to toggle VR mode on/off
    vr_settings = VrSettings()
    if not is_save:
        vr_settings.turn_off_vr_mode()
    s = Simulator(mode='vr', 
                rendering_settings=vr_rendering_settings, 
                vr_settings=vr_settings)
    scene = InteractiveIndoorScene('Rs_int')
    scene._set_first_n_objects(2)
    s.import_ig_scene(scene)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())

    # Create a VrAgent and it will handle all initialization and importing under-the-hood
    # Data replay uses constraints during both save and replay modes
    vr_agent = VrAgent(s, use_constraints=True)
    
    if is_save:
        # Since vr_height_offset is set, we will use the VR HMD true height plus this offset instead of the third entry of the start pos
        s.set_vr_start_pos([0, 0, 0], vr_height_offset=-0.1)

    # Objects to interact with
    objects = [
        ("jenga/jenga.urdf", (1.300000, -0.700000, 0.750000), (0.000000, 0.707107, 0.000000,
                0.707107)),
        ("jenga/jenga.urdf", (1.200000, -0.700000, 0.750000), (0.000000, 0.707107, 0.000000,
                0.707107)),
        ("jenga/jenga.urdf", (1.100000, -0.700000, 0.750000), (0.000000, 0.707107, 0.000000,
                0.707107)),
        ("jenga/jenga.urdf", (1.000000, -0.700000, 0.750000), (0.000000, 0.707107, 0.000000,
                0.707107)),
        ("jenga/jenga.urdf", (0.900000, -0.700000, 0.750000), (0.000000, 0.707107, 0.000000,
                0.707107)),
        ("jenga/jenga.urdf", (0.800000, -0.700000, 0.750000), (0.000000, 0.707107, 0.000000,
                0.707107)),
        ("table/table.urdf", (1.000000, -0.200000, 0.000000), (0.000000, 0.000000, 0.707107,
                0.707107)),
        ("duck_vhacd.urdf", (1.050000, -0.500000, 0.700000), (0.000000, 0.000000, 0.707107,
                0.707107)),
        ("duck_vhacd.urdf", (0.950000, -0.100000, 0.700000), (0.000000, 0.000000, 0.707107,
                0.707107)),
        ("sphere_small.urdf", (0.850000, -0.400000, 0.700000), (0.000000, 0.000000, 0.707107,
                0.707107)),
        ("duck_vhacd.urdf", (0.850000, -0.400000, 1.00000), (0.000000, 0.000000, 0.707107,
                0.707107)),
    ]

    for item in objects:
        fpath = item[0]
        pos = item[1]
        orn = item[2]
        item_ob = ArticulatedObject(fpath, scale=1)
        s.import_object(item_ob, use_pbr=False, use_pbr_mapping=False)
        item_ob.set_position(pos)
        item_ob.set_orientation(orn)

    for i in range(3):
        obj = YCBObject('003_cracker_box')
        s.import_object(obj)
        obj.set_position_orientation([1.100000 + 0.12 * i, -0.300000, 0.750000], [0, 0, 0, 1])

    obj = ArticulatedObject(os.path.join(gibson2.ig_dataset_path, 'objects', 
        'basket', 'e3bae8da192ab3d4a17ae19fa77775ff', 'e3bae8da192ab3d4a17ae19fa77775ff.urdf'),
                            scale=2)
    s.import_object(obj)
    obj.set_position_orientation([1.1, 0.300000, 1.2], [0, 0, 0, 1])

    # Note: Modify this path to save to different files
    vr_log_path = 'vr_logs/vr_actions_sr.h5'
    mock_vr_action_path = 'mock_vr_action'

    if mode == 'save':
        # Saves every 2 seconds or so (200 / 90fps is approx 2 seconds)
        vr_writer = VRLogWriter(frames_before_write=200, log_filepath=vr_log_path, profiling_mode=False, log_status=False)

        # Save a single button press as a mock action that demonstrates action-saving capabilities.
        vr_writer.register_action(mock_vr_action_path, (1,))

        # Call set_up_data_storage once all actions have been registered (in this demo we only save states so there are none)
        # Despite having no actions, we need to call this function
        vr_writer.set_up_data_storage()
    else:
        # Playback faster than FPS during saving - can set emulate_save_fps to True to emulate saving FPS
        vr_reader = VRLogReader(vr_log_path, s, emulate_save_fps=False, log_status=False)

    if is_save:
        # Main simulation loop - run for as long as the user specified
        for i in range(FRAMES_TO_SAVE):
            s.step()

            # Example of storing a simple mock action
            vr_writer.save_action(mock_vr_action_path, np.array([1]))

            # Update VR objects
            vr_agent.update()

            # Print debugging information
            if PRINT_PB:
                vr_writer._print_pybullet_data()

            # Record this frame's data in the VRLogWriter
            vr_writer.process_frame(s, print_vr_data=PRINT_VR_DATA)

        # Note: always call this after the simulation is over to close the log file
        # and clean up resources used.
        vr_writer.end_log_session()
    else:
        # The VR reader automatically shuts itself down and performs cleanup once the while loop has finished running
        while vr_reader.get_data_left_to_read():
            vr_reader.pre_step()
            # Don't sleep until the frame duration, as the VR logging system sleeps for this duration instead
            s.step(forced_timestep=vr_reader.get_phys_step_n())

            # Note that fullReplay is set to False for action replay
            vr_reader.read_frame(s, full_replay=False, print_vr_data=PRINT_VR_DATA)

            # Read our mock action (but don't do anything with it for now)
            mock_action = int(vr_reader.read_action(mock_vr_action_path)[0])

            # Get relevant VR action data and update VR agent
            vr_action_data = vr_reader.get_vr_action_data()
            vr_agent.update(vr_action_data)

            # Print debugging information
            if PRINT_PB:
                vr_reader._print_pybullet_data()

    s.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='VR state saving and replay demo')
    parser.add_argument('--mode', default='save', help='Mode to run in: either save or replay')
    args = parser.parse_args()
    run_action_sr(mode=args.mode)