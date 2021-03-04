from gibson2.object_states.aabb import AABB
from gibson2.object_states.cleaning_tool import CleaningTool
from gibson2.object_states.soaked import Soaked
from gibson2.object_states.object_state_base import AbsoluteObjectState
from gibson2.object_states.object_state_base import BooleanState
from gibson2.objects.particles import Dirt

CLEAN_THRESHOLD = 0.9

class Stained(AbsoluteObjectState, BooleanState):

    def __init__(self, obj):
        super(Stained, self).__init__(obj)
        self.prev_value = False
        self.value = False
        self.stain = None

    def get_value(self):
        return self.value

    def set_value(self, new_value):
        self.value = new_value
        if not self.value:
            for particle in self.stain.particles:
                self.stain.stash_particle(particle)

    def update(self, simulator):
        # Nothing to do if not stained.
        if not self.value:
            return

        # Load the stain if necessary.
        if self.stain is None:
            self.stain = Dirt(self.obj)
            simulator.import_particle_system(self.stain)

        # Attach if we went to stained in this step.
        if self.value and not self.prev_value:
            self.stain.randomize(self.obj)

        # cleaning logic
        cleaning_tools = simulator.scene.get_objects_with_state(CleaningTool)
        cleaning_tools_wet = []
        for tool in cleaning_tools:
            if Soaked in tool.states and tool.states[Soaked].get_value():
                cleaning_tools_wet.append(tool)

        for object in cleaning_tools_wet:
            for particle in self.stain.get_active_particles():
                particle_pos = particle.get_position()
                aabb = object.states[AABB].get_value()
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
                    self.stain.stash_particle(particle)

        # update self.value based on particle count
        self.prev_value = self.value
        self.value = self.stain.get_num_active() > self.stain.get_num() * CLEAN_THRESHOLD


    @staticmethod
    def get_dependencies():
        return [AABB]

    @staticmethod
    def get_optional_dependencies():
        return [Soaked, CleaningTool]