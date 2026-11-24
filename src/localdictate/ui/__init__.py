"""PyQt6 Studio 2.0 UI components for LocalDictate."""

from .overlay import FloatingOverlay
from .studio_window import StudioWindow
from .tray import TrayManager
from .widgets import (
    FlatComboBox,
    FlatSwitch,
    LiveWaveformBar,
    SidebarNavButton,
    TelemetryCard,
    create_app_icon,
    create_app_pixmap,
    make_flat_icon,
)

__all__ = [
    "FloatingOverlay",
    "StudioWindow",
    "TrayManager",
    "FlatComboBox",
    "FlatSwitch",
    "LiveWaveformBar",
    "SidebarNavButton",
    "TelemetryCard",
    "create_app_icon",
    "create_app_pixmap",
    "make_flat_icon",
]
