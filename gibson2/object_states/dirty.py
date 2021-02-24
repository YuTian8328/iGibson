from gibson2.object_states.object_state_base import AbsoluteObjectState
from gibson2.object_states.object_state_base import BooleanState
from gibson2.objects.particles import Dust

CLEAN_THRESHOLD = 0.9

class Dirty(AbsoluteObjectState, BooleanState):

    def __init__(self, obj):
        super(Dirty, self).__init__(obj)
        self.value = False
        self.dust = Dust()
        self.dust.register_parent_obj(self.obj)

    def get_value(self):
        return self.value

    def set_value(self, new_value):
        self.value = new_value
        if self.value:
            self.dust.attach(self.obj)
            for particle in self.dust.particles:
                particle.active = True
        else:
            for particle in self.dust.particles:
                self.dust.stash_particle(particle)

    def update(self, simulator):
        # cleaning logic
        cleaning_tools = simulator.scene.get_objects_with_state("cleaning_tool")
        for object in cleaning_tools:
            for particle in self.dust.particles:
                particle_pos = particle.get_position()
                aabb = object.states["aabb"].get_value()
                xmin = aabb[0][0]
                xmax = aabb[1][0]
                ymin = aabb[0][1]
                ymax = aabb[1][1]
                zmin = aabb[0][2]
                zmax = aabb[1][2]

                # inflate aabb
                xmin -= (xmax - xmin) * 0.1
                xmax += (xmax - xmin) * 0.1
                ymin -= (ymax - ymin) * 0.1
                ymax += (ymax - ymin) * 0.1
                zmin -= (zmax - zmin) * 0.1
                zmax += (zmax - zmin) * 0.1

                if particle_pos[0] > xmin and particle_pos[0] < xmax and particle_pos[1] > ymin and particle_pos[1] < \
                    ymax and particle_pos[2] > zmin and particle_pos[2] < zmax:
                    self.dust.stash_particle(particle)

        # update self.value based on particle count
        self.value = self.dust.get_num_active() > self.dust.get_num() * CLEAN_THRESHOLD

    @staticmethod
    def get_dependencies():
        return ["aabb"]

    @staticmethod
    def get_optional_dependencies():
        return ["cleaning_tool"]