import networkx as nx
from gibson2.object_states.aabb import AABB
from gibson2.object_states.burnt import Burnt
from gibson2.object_states.contact_bodies import ContactBodies
from gibson2.object_states.cooked import Cooked
from gibson2.object_states.dummy_state import DummyState
from gibson2.object_states.heat_source import HeatSource
from gibson2.object_states.inside import Inside
from gibson2.object_states.max_temperature import MaxTemperature
from gibson2.object_states.next_to import NextTo
from gibson2.object_states.on_top import OnTop
from gibson2.object_states.open import Open
from gibson2.object_states.pose import Pose
from gibson2.object_states.temperature import Temperature
from gibson2.object_states.touching import Touching
from gibson2.object_states.under import Under
from gibson2.object_states.soaked import Soaked
from gibson2.object_states.dirty import Dirty
from gibson2.object_states.stained import Stained
from gibson2.object_states.toggle import ToggledOn
from gibson2.object_states.water_source import WaterSource
from gibson2.object_states.cleaning_tool import CleaningTool


_STATE_NAME_TO_CLASS_MAPPING = {
    # Kinematic states
    'pose': Pose,
    'aabb': AABB,
    'contact_bodies': ContactBodies,
    'onTop': OnTop,
    'open': Open,
    'inside': Inside,
    'nextTo': NextTo,
    'under': Under,
    'touching': Touching,
    'toggled_on': ToggledOn,
    # Particle-related states
    'soaked': Soaked,
    'dirty': Dirty,
    'stained': Stained,
    'water_source': WaterSource,
    'cleaning_tool': CleaningTool,
    # Temperature / cooking states
    'heatSource': HeatSource,
    'temperature': Temperature,
    'maxTemperature': MaxTemperature,
    'burnt': Burnt,
    'cooked': Cooked,
}

_ABILITY_TO_STATE_MAPPING = {
    "cookable": ["cooked"],
    "soakable": ["soaked"],
    "dustable": ["dirty"],
    "scrubbable": ["stained"],
    "water_source": ["water_source"],
    "cleaning_tool": ["cleaning_tool"],
    "toggleable": ["toggled_on"],
    "burnable": ["burnt"],
    "heatSource": ["heatSource"]
}

_DEFAULT_STATE_SET = {
    'onTop',
    'inside',
    'nextTo',
    'under',
    'touching',
    'open',
}


def get_default_state_names():
    return set(_DEFAULT_STATE_SET)


def get_all_state_names():
    return set(_STATE_NAME_TO_CLASS_MAPPING.keys())


def get_state_names_for_ability(ability):
    return _ABILITY_TO_STATE_MAPPING[ability]


def get_object_state_instance(state_name, obj, params=None, online=True):
    """
    Create an BaseObjectState child class instance for a given object & state.

    The parameters passed in as a dictionary through params are passed as
    kwargs to the object state class constructor.

    :param state_name: The state name from the state name dictionary.
    :param obj: The object for which the state is being constructed.
    :param params: Dict of {param: value} corresponding to the state's params.
    :param online: Whether or not the instance should be generated for an online
        object. Offline mode involves using dummy objects rather than real state
        objects.
    :return: The constructed state object, an instance of a child of
        BaseObjectState.
    """
    if state_name not in _STATE_NAME_TO_CLASS_MAPPING:
        assert False, 'unknown state name: {}'.format(state_name)

    if not online:
        return DummyState(obj)

    state_class = _STATE_NAME_TO_CLASS_MAPPING[state_name]

    if params is None:
        params = {}

    return state_class(obj, **params)


def prepare_object_states(obj, abilities=None, online=True):
    """
    Prepare the state dictionary for an object by generating the appropriate
    object state instances.

    This uses the abilities of the object and the state dependency graph to
    find & instantiate all relevant states.

    :param obj: The object to generate states for.
    :param abilities: dict in the form of {ability: {param: value}} containing
        object abilities and parameters.
    :param online: Whether or not the states should be generated for an online
        object. Offline mode involves using dummy objects rather than real state
        objects.
    """
    if abilities is None:
        abilities = {}

    state_names_and_params = [(state_name, {}) for state_name in get_default_state_names()]

    # Map the ability params to the states immediately imported by the abilities
    for ability, params in abilities.items():
        state_names_and_params.extend((state_name, params) for state_name in get_state_names_for_ability(ability))

    obj.states = dict()
    for state_name, params in state_names_and_params:
        obj.states[state_name] = get_object_state_instance(state_name, obj, params)

        # Add each state's dependencies, too. Note that only required dependencies are added.
        for dependency in obj.states[state_name].get_dependencies():
            if dependency not in state_names_and_params:
                state_names_and_params.append((dependency, {}))


def get_state_dependency_graph():
    """
    Produce dependency graph of supported object states.
    """
    dependencies = {
        state_name: (
                _STATE_NAME_TO_CLASS_MAPPING[state_name].get_dependencies() +
                _STATE_NAME_TO_CLASS_MAPPING[state_name].get_optional_dependencies())
        for state_name in get_all_state_names()}
    return nx.DiGraph(dependencies)


def get_states_by_dependency_order():
    """
    Produce a list of all states in topological order of dependency.
    """
    return list(reversed(list(nx.algorithms.topological_sort(get_state_dependency_graph()))))
