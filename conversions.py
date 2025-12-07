"""
Unit Conversion Functions for OBD-Gauge

Common conversions for OBD2 data (temperature, pressure, etc.)
"""

from typing import Callable

# Conversion function type
ConversionFunc = Callable[[float], float]


def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return (c * 1.8) + 32


def fahrenheit_to_celsius(f: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (f - 32) / 1.8


def kpa_to_psi(kpa: float) -> float:
    """Convert kiloPascals to PSI."""
    return kpa * 0.145038


def psi_to_kpa(psi: float) -> float:
    """Convert PSI to kiloPascals."""
    return psi * 6.89476


def kpa_to_bar(kpa: float) -> float:
    """Convert kiloPascals to bar."""
    return kpa / 100


def bar_to_kpa(bar: float) -> float:
    """Convert bar to kiloPascals."""
    return bar * 100


def bar_to_psi(bar: float) -> float:
    """Convert bar to PSI."""
    return bar * 14.503774


def psi_to_bar(psi: float) -> float:
    """Convert PSI to bar."""
    return psi * 0.0689476


def kmh_to_mph(kmh: float) -> float:
    """Convert km/h to mph."""
    return kmh * 0.621371


def mph_to_kmh(mph: float) -> float:
    """Convert mph to km/h."""
    return mph * 1.60934


def liters_to_gallons(liters: float) -> float:
    """Convert liters to US gallons."""
    return liters * 0.264172


def gallons_to_liters(gallons: float) -> float:
    """Convert US gallons to liters."""
    return gallons * 3.78541


def identity(x: float) -> float:
    """No conversion (pass-through)."""
    return x


# Dictionary of available conversions
# Key is the conversion ID used in config
CONVERSIONS: dict[str, ConversionFunc] = {
    "none": identity,
    "c_to_f": celsius_to_fahrenheit,
    "f_to_c": fahrenheit_to_celsius,
    "kpa_to_psi": kpa_to_psi,
    "psi_to_kpa": psi_to_kpa,
    "kpa_to_bar": kpa_to_bar,
    "bar_to_kpa": bar_to_kpa,
    "bar_to_psi": bar_to_psi,
    "psi_to_bar": psi_to_bar,
    "kmh_to_mph": kmh_to_mph,
    "mph_to_kmh": mph_to_kmh,
    "l_to_gal": liters_to_gallons,
    "gal_to_l": gallons_to_liters,
}

# Human-readable names for settings UI
CONVERSION_NAMES: dict[str, str] = {
    "none": "None",
    "c_to_f": "Celsius → Fahrenheit",
    "f_to_c": "Fahrenheit → Celsius",
    "kpa_to_psi": "kPa → PSI",
    "psi_to_kpa": "PSI → kPa",
    "kpa_to_bar": "kPa → bar",
    "bar_to_kpa": "bar → kPa",
    "bar_to_psi": "bar → PSI",
    "psi_to_bar": "PSI → bar",
    "kmh_to_mph": "km/h → mph",
    "mph_to_kmh": "mph → km/h",
    "l_to_gal": "Liters → Gallons",
    "gal_to_l": "Gallons → Liters",
}


def get_conversion(conversion_id: str) -> ConversionFunc:
    """
    Get a conversion function by ID.

    Args:
        conversion_id: Conversion identifier (e.g., "c_to_f")

    Returns:
        Conversion function, or identity if not found
    """
    return CONVERSIONS.get(conversion_id, identity)


def convert(value: float, conversion_id: str) -> float:
    """
    Apply a conversion to a value.

    Args:
        value: Input value
        conversion_id: Conversion identifier

    Returns:
        Converted value
    """
    return get_conversion(conversion_id)(value)


if __name__ == "__main__":
    # Test conversions
    print("Testing conversions:")
    print(f"  100°C -> {celsius_to_fahrenheit(100):.1f}°F")
    print(f"  212°F -> {fahrenheit_to_celsius(212):.1f}°C")
    print(f"  100 kPa -> {kpa_to_psi(100):.2f} PSI")
    print(f"  14.5 PSI -> {psi_to_kpa(14.5):.2f} kPa")
    print(f"  2 bar -> {bar_to_psi(2):.2f} PSI")
    print(f"  100 km/h -> {kmh_to_mph(100):.1f} mph")
