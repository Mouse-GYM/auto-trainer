import pytest

from tools.acquisition.model.behavior_model import EmergencyControlSource


known_admin_sources = (
    EmergencyControlSource.USER_BUTTON.value,
    EmergencyControlSource.RPC_SERVICE.value,
)


known_not_other_sources = known_admin_sources  # for now


not_admin_sources = tuple(
    set(map(str, EmergencyControlSource)) - set(known_admin_sources)
) + ('unknown1', 'other2')


@pytest.mark.parametrize("src", known_not_other_sources)
def test_is_not_other(src):
    assert EmergencyControlSource(src) is not EmergencyControlSource.OTHER


@pytest.mark.parametrize("src", ["unknown1", "other2"])
def test_is_other(src):
    assert EmergencyControlSource(src) is EmergencyControlSource.OTHER


@pytest.mark.parametrize("src", known_admin_sources)
def test_is_admin(src):
    assert EmergencyControlSource(src).is_admin_source()


@pytest.mark.parametrize("src", not_admin_sources)
def test_is_not_admin(src):
    assert not EmergencyControlSource(src).is_admin_source()
