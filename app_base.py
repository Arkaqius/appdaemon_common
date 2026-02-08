"""Base class and init flow utilities for AppDaemon apps."""

from __future__ import annotations

import datetime as _dt
import itertools
import traceback
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # AppDaemon runtime
    import appdaemon.plugins.hass.hassapi as hass
except Exception:  # pragma: no cover - allow import outside AD
    hass = None  # type: ignore

_InitMeta = Tuple[int, str, str]

_init_counter = itertools.count()


def init_step(name: str, order: Optional[int] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to mark an init step for ordered initialization.

    Example:
        @init_step("config")
        def init_config(self):
            ...
    """
    if order is None:
        order = next(_init_counter)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, "__init_step__", {"name": name, "order": order})
        return fn

    return decorator


def safe_callback(
    name: Optional[str] = None,
    *,
    health: str = "degraded",
    reraise: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Wrap a callback to catch exceptions and report health.

    If the instance provides handle_callback_exception(), it will be used.
    Otherwise it will log the exception via self.log when available.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        cb_name = name or fn.__name__

        @wraps(fn)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return fn(self, *args, **kwargs)
            except Exception as exc:  # pragma: no cover - runtime protection
                if hasattr(self, "handle_callback_exception"):
                    self.handle_callback_exception(
                        exc, callback_name=cb_name, health=health, reraise=reraise
                    )
                    return None
                if hasattr(self, "log"):
                    self.log(f"Callback error '{cb_name}': {exc}", level="ERROR")
                    if reraise:
                        raise
                    return None
                if reraise:
                    raise
                return None

        return wrapper

    return decorator


class AppBase(hass.Hass if hass else object):
    """Base class for AppDaemon apps with init flow, scheduling, and safe state helpers."""

    def initialize(self) -> None:
        """Initialize internal registries and run declared init steps."""
        # Internal registries
        if not hasattr(self, "_timers"):
            self._timers: Dict[str, Any] = {}
        if not hasattr(self, "_listeners"):
            self._listeners: Dict[str, Any] = {}
        if not hasattr(self, "_safe_state_entered"):
            self._safe_state_entered = False
        if not hasattr(self, "_app_started_at"):
            self._app_started_at = _dt.datetime.now(_dt.timezone.utc)

        # Run declarative init steps if present
        self.run_init_steps()

    # ---- Init flow ----
    def run_init_steps(self) -> None:
        """Execute init steps declared with @init_step in order."""
        steps = self._collect_init_steps()
        if not steps:
            return

        for _order, step_name, method_name in steps:
            try:
                self.log(f"Init step: {step_name}", level="DEBUG")
                getattr(self, method_name)()
            except Exception as exc:
                self.handle_init_exception(exc, step_name=step_name)
                raise

    def _collect_init_steps(self) -> List[_InitMeta]:
        steps: List[_InitMeta] = []
        seen: set[str] = set()

        # Walk MRO from subclass -> base so overrides take precedence
        for cls in self.__class__.mro():
            for name, value in cls.__dict__.items():
                if name in seen:
                    continue
                if callable(value) and hasattr(value, "__init_step__"):
                    meta = getattr(value, "__init_step__")
                    steps.append((meta["order"], meta["name"], name))
                    seen.add(name)

        return sorted(steps, key=lambda s: s[0])

    # ---- Exception handling ----
    def handle_init_exception(self, exc: Exception, step_name: Optional[str] = None) -> None:
        """Handle errors during init steps and mark health if available."""
        step_label = f" step '{step_name}'" if step_name else ""
        self.log(
            f"Init error{step_label}: {exc}\n{traceback.format_exc()}",
            level="ERROR",
        )
        # Best-effort health update if available
        if hasattr(self, "mark_faulted"):
            try:
                self.mark_faulted(exc)
            except Exception:
                pass

    def handle_callback_exception(
        self,
        exc: Exception,
        callback_name: Optional[str] = None,
        health: str = "degraded",
        reraise: bool = False,
    ) -> None:
        """Handle callback exceptions and mark health as degraded/faulted."""
        cb_label = f" callback '{callback_name}'" if callback_name else ""
        self.log(
            f"Callback error{cb_label}: {exc}\n{traceback.format_exc()}",
            level="ERROR",
        )
        # Best-effort health update if available
        try:
            if health == "faulted" and hasattr(self, "mark_faulted"):
                self.mark_faulted(exc)
            elif hasattr(self, "mark_degraded"):
                self.mark_degraded(exc)
        except Exception:
            pass

        if reraise:
            raise exc

    # ---- Safe state ----
    def enter_safe_state(
        self,
        reason: str,
        *,
        stop_timers: bool = True,
        stop_listeners: bool = True,
        health_state: str = "faulted",
    ) -> None:
        """Isolate the app by cancelling timers/listeners and updating health."""
        if getattr(self, "_safe_state_entered", False):
            return
        self._safe_state_entered = True

        self.log(f"Entering safe state: {reason}", level="ERROR")

        if stop_timers:
            self.cancel_all_timers()
        if stop_listeners:
            self.cancel_all_listeners()

        if health_state == "faulted" and hasattr(self, "mark_faulted"):
            try:
                self.mark_faulted(reason)
            except Exception:
                pass
        elif health_state == "degraded" and hasattr(self, "mark_degraded"):
            try:
                self.mark_degraded(reason)
            except Exception:
                pass

        try:
            self.on_enter_safe_state()
        except Exception as exc:
            self.log(f"Safe state hook failed: {exc}", level="ERROR")

    def on_enter_safe_state(self) -> None:
        """Optional hook for app-specific safe state actions."""
        return None

    # ---- Scheduling helpers ----
    def schedule_once(
        self,
        name: str,
        seconds: int,
        callback: Callable[..., Any],
        **kwargs: Any,
    ) -> Any:
        """Schedule a one-shot callback and store its handle by name."""
        handle = self.run_in(callback, seconds, **kwargs)
        self._timers[name] = handle
        return handle

    def schedule_every(
        self,
        name: str,
        start_time: _dt.datetime,
        interval: int,
        callback: Callable[..., Any],
        **kwargs: Any,
    ) -> Any:
        """Schedule a repeating callback and store its handle by name."""
        handle = self.run_every(callback, start_time, interval, **kwargs)
        self._timers[name] = handle
        return handle

    def schedule_daily(
        self,
        name: str,
        time_obj: _dt.time,
        callback: Callable[..., Any],
        **kwargs: Any,
    ) -> Any:
        """Schedule a daily callback and store its handle by name."""
        handle = self.run_daily(callback, time_obj, **kwargs)
        self._timers[name] = handle
        return handle

    def cancel_timer_by_name(self, name: str, *, force: bool = False) -> None:
        """Cancel a named timer; heartbeat is protected unless force=True."""
        if not force and name == "heartbeat":
            return
        handle = self._timers.get(name)
        if handle is None:
            return
        try:
            self.cancel_timer(handle)
        except Exception:
            pass
        self._timers.pop(name, None)

    def cancel_all_timers(self, *, exclude: Optional[List[str]] = None) -> None:
        """Cancel all timers except those in exclude (defaults to heartbeat)."""
        if exclude is None:
            exclude = ["heartbeat"]
        for name in list(self._timers.keys()):
            if name in exclude:
                continue
            self.cancel_timer_by_name(name, force=True)

    # ---- Listener helpers ----
    def listen_state_named(
        self,
        name: str,
        callback: Callable[..., Any],
        entity: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Register a state listener and store its handle by name."""
        handle = self.listen_state(callback, entity, **kwargs)
        self._listeners[name] = handle
        return handle

    def cancel_listen_by_name(self, name: str) -> None:
        """Cancel a named state listener if present."""
        handle = self._listeners.get(name)
        if handle is None:
            return
        try:
            self.cancel_listen_state(handle)
        except Exception:
            pass
        self._listeners.pop(name, None)

    def cancel_all_listeners(self) -> None:
        """Cancel all registered state listeners."""
        for name in list(self._listeners.keys()):
            self.cancel_listen_by_name(name)
