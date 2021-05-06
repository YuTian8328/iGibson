from gibson2.object_states.object_state_base import CachingEnabledObjectState
import pybullet as p


class ContactBodies(CachingEnabledObjectState):
    def _compute_value(self):
        body_id = self.obj.get_body_id()
        return [item for item in p.getContactPoints(bodyA=body_id)]

    def set_value(self, new_value):
        raise NotImplementedError(
            "ContactBodies state currently does not support setting.")
