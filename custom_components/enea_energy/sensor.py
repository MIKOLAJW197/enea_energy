"""Sensors for the Enea Energy integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
    """Set up sensors for a config entry."""
    coordinator: EneaEnergyCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            EneaEnergyBalanceSensor(coordinator),
            EneaPeriodImportSensor(coordinator),
            EneaPeriodExportSensor(coordinator),
        ]
    )


class _EneaPeriodSensor(CoordinatorEntity[EneaEnergyCoordinator], SensorEntity):
    """Shared base for billing-period energy sensors."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    _data_key: str

    def __init__(self, coordinator: EneaEnergyCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._data_key)
        if value is None:
            return None
        return round(float(value), 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        data = self.coordinator.data
        return {
            "balance_period_start": data.get("balance_period_start"),
            "balance_period_end": data.get("balance_period_end"),
            "configured_start_date": data.get("configured_start_date"),
            "export_recovery_percent": data.get("export_recovery_percent"),
            "refreshed_at": data.get("refreshed_at"),
        }


class EneaEnergyBalanceSensor(_EneaPeriodSensor):
    """Energy balance for the billing period: recovered export − grid import."""

    _attr_translation_key = "energy_balance"
    _attr_icon = "mdi:scale-balance"
    _data_key = "energy_balance_kwh"

    def __init__(self, coordinator: EneaEnergyCoordinator) -> None:
        super().__init__(coordinator, "energy_balance")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        base = super().extra_state_attributes
        if base is None or self.coordinator.data is None:
            return base
        data = self.coordinator.data
        return {
            **base,
            "period_import_kwh": data.get("period_import_kwh"),
            "period_export_kwh": data.get("period_export_kwh"),
        }


class EneaPeriodImportSensor(_EneaPeriodSensor):
    """Grid import (pobrana) in the current billing period."""

    _attr_translation_key = "period_import"
    _attr_icon = "mdi:transmission-tower-import"
    _data_key = "period_import_kwh"

    def __init__(self, coordinator: EneaEnergyCoordinator) -> None:
        super().__init__(coordinator, "period_import")


class EneaPeriodExportSensor(_EneaPeriodSensor):
    """Raw grid export (oddana) in the current billing period — no recovery %."""

    _attr_translation_key = "period_export"
    _attr_icon = "mdi:transmission-tower-export"
    _data_key = "period_export_kwh"

    def __init__(self, coordinator: EneaEnergyCoordinator) -> None:
        super().__init__(coordinator, "period_export")
