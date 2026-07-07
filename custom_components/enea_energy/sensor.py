"""Sensory integracji Enea Energy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EneaEnergyCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Konfiguracja sensorów."""
    coordinator: EneaEnergyCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([EneaEnergyBalanceSensor(coordinator)])


class EneaEnergyBalanceSensor(CoordinatorEntity[EneaEnergyCoordinator], SensorEntity):
    """Bilans energii: oddanie (× % odbioru) minus pobór z sieci."""

    _attr_has_entity_name = True
    _attr_translation_key = "energy_balance"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:scale-balance"

    def __init__(self, coordinator: EneaEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_energy_balance"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("energy_balance_kwh")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        data = self.coordinator.data
        return {
            "period_import_kwh": data.get("period_import_kwh"),
            "period_export_kwh": data.get("period_export_kwh"),
            "balance_period_start": data.get("balance_period_start"),
            "configured_start_date": data.get("configured_start_date"),
            "export_recovery_percent": data.get("export_recovery_percent"),
            "last_data_date": data.get("last_data_date"),
        }
