#!/usr/bin/env python3
"""
Bluetooth RFCOMM Server using D-Bus API (BlueZ 5.x)

This is the proper modern implementation that:
1. Registers a custom Agent for automatic pairing (NoInputNoOutput)
2. Registers an SPP Profile via D-Bus ProfileManager1
3. Handles file descriptors correctly with fd.take()

Based on BlueZ 5.x D-Bus API specifications.
"""

import sys
import os
import socket
import threading
import signal
import time
import traceback

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# Add parent directory for simulator import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulator import OBDSimulator

# BlueZ D-Bus constants
BLUEZ_SERVICE = "org.bluez"
ADAPTER_INTERFACE = "org.bluez.Adapter1"
DEVICE_INTERFACE = "org.bluez.Device1"
AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_MANAGER_INTERFACE = "org.bluez.AgentManager1"
PROFILE_INTERFACE = "org.bluez.Profile1"
PROFILE_MANAGER_INTERFACE = "org.bluez.ProfileManager1"

# SPP UUID
SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"

# D-Bus object paths
AGENT_PATH = "/com/obd/agent"
PROFILE_PATH = "/com/obd/spp"


class AutoPairAgent(dbus.service.Object):
    """
    Bluetooth pairing agent that automatically accepts all pairing requests.
    Implements org.bluez.Agent1 interface for headless operation.
    """

    def __init__(self, bus, path):
        dbus.service.Object.__init__(self, bus, path)
        self.bus = bus
        print(f"[Agent] Initialized at {path}", file=sys.stderr)

    def set_trusted(self, device_path):
        """Mark a device as trusted."""
        try:
            device = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE, device_path),
                "org.freedesktop.DBus.Properties"
            )
            device.Set(DEVICE_INTERFACE, "Trusted", dbus.Boolean(True))
            print(f"[Agent] Device trusted: {device_path}", file=sys.stderr)
        except Exception as e:
            print(f"[Agent] Failed to trust device: {e}", file=sys.stderr)

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        """Called when agent is unregistered."""
        print("[Agent] Released", file=sys.stderr)

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """Authorize a service connection - auto-accept."""
        print(f"[Agent] AuthorizeService: {device} UUID={uuid}", file=sys.stderr)
        self.set_trusted(device)
        return  # Implicit accept

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """Return PIN code for pairing."""
        print(f"[Agent] RequestPinCode: {device}", file=sys.stderr)
        self.set_trusted(device)
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """Return passkey for pairing."""
        print(f"[Agent] RequestPasskey: {device}", file=sys.stderr)
        self.set_trusted(device)
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        """Display passkey (we just log it)."""
        print(f"[Agent] DisplayPasskey: {device} passkey={passkey}", file=sys.stderr)

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """Display PIN code (we just log it)."""
        print(f"[Agent] DisplayPinCode: {device} pin={pincode}", file=sys.stderr)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        """Confirm passkey - auto-accept."""
        print(f"[Agent] RequestConfirmation: {device} passkey={passkey}", file=sys.stderr)
        self.set_trusted(device)
        return  # Implicit accept

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        """Authorize connection - auto-accept."""
        print(f"[Agent] RequestAuthorization: {device}", file=sys.stderr)
        self.set_trusted(device)
        return  # Implicit accept

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        """Cancel current operation."""
        print("[Agent] Cancelled", file=sys.stderr)


class SPPProfile(dbus.service.Object):
    """
    Serial Port Profile implementation.
    Implements org.bluez.Profile1 interface.
    """

    def __init__(self, bus, path, simulator):
        dbus.service.Object.__init__(self, bus, path)
        self.bus = bus
        self.simulator = simulator
        self.connections = {}  # fd -> thread
        print(f"[Profile] Initialized at {path}", file=sys.stderr)

    @dbus.service.method(PROFILE_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        """Called when profile is unregistered."""
        print("[Profile] Released", file=sys.stderr)
        # Close all active connections
        for fd in list(self.connections.keys()):
            try:
                os.close(fd)
            except:
                pass
        self.connections.clear()

    @dbus.service.method(PROFILE_INTERFACE, in_signature="oha{sv}", out_signature="")
    def NewConnection(self, device_path, fd, properties):
        """
        Called when a new connection is established.

        CRITICAL: We must take ownership of the file descriptor immediately!
        The 'fd' parameter is a dbus.types.UnixFd object. We call .take() to
        transfer ownership to our code. Without this, the FD is closed when
        the D-Bus message is processed.
        """
        # Take ownership of the file descriptor
        fd_num = fd.take()

        print(f"[Profile] NewConnection: device={device_path} fd={fd_num}", file=sys.stderr)
        print(f"[Profile] Properties: {dict(properties)}", file=sys.stderr)

        # Handle the connection in a thread using the raw fd
        try:
            # Start a handler thread for this connection
            # Pass fd_num directly - we'll use os.read/os.write
            thread = threading.Thread(
                target=self._handle_client_fd,
                args=(fd_num, device_path),
                daemon=True
            )
            self.connections[fd_num] = thread
            thread.start()
            print(f"[Profile] Handler thread started for fd={fd_num}", file=sys.stderr)

        except Exception as e:
            print(f"[Profile] Error starting handler: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            try:
                os.close(fd_num)
            except:
                pass

    @dbus.service.method(PROFILE_INTERFACE, in_signature="o", out_signature="")
    def RequestDisconnection(self, device_path):
        """Called when disconnection is requested."""
        print(f"[Profile] RequestDisconnection: {device_path}", file=sys.stderr)

    def _handle_client_fd(self, fd_num, device_path):
        """Handle OBD commands from a connected client using raw fd."""
        print(f"[Handler] Started for fd={fd_num}", file=sys.stderr)

        # Set fd to blocking mode
        import fcntl
        flags = fcntl.fcntl(fd_num, fcntl.F_GETFL)
        fcntl.fcntl(fd_num, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)

        # Send initial prompt
        try:
            os.write(fd_num, b">")
            print(f"[Handler] Sent initial prompt", file=sys.stderr)
        except Exception as e:
            print(f"[Handler] Error sending prompt: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return

        buffer = ""

        try:
            while True:
                try:
                    data = os.read(fd_num, 1024)
                except OSError as e:
                    print(f"[Handler] Read error: {e}", file=sys.stderr)
                    break

                if not data:
                    print(f"[Handler] Client disconnected (EOF)", file=sys.stderr)
                    break

                print(f"[Handler] Received {len(data)} bytes: {data!r}", file=sys.stderr)
                buffer += data.decode('utf-8', errors='ignore')

                # Process complete commands (terminated by CR or LF)
                while '\r' in buffer or '\n' in buffer:
                    # Find first terminator
                    idx = len(buffer)
                    if '\r' in buffer:
                        idx = min(idx, buffer.find('\r'))
                    if '\n' in buffer:
                        idx = min(idx, buffer.find('\n'))

                    cmd = buffer[:idx]
                    buffer = buffer[idx+1:].lstrip('\r\n')

                    if cmd:
                        # Filter out echoed responses (starts with > or is just ?)
                        # The gauge app echoes our responses back
                        clean_cmd = cmd.strip().lstrip('>').strip()
                        if clean_cmd and clean_cmd != '?' and not clean_cmd.startswith('^'):
                            print(f"[Handler] Command: {clean_cmd}", file=sys.stderr)
                            response = self.simulator.process_command(clean_cmd)
                            output = self.simulator.format_output(response)
                            try:
                                os.write(fd_num, output.encode())
                                os.fsync(fd_num)  # Force flush to BT stack
                                print(f"[Handler] Sent: {output!r}", file=sys.stderr)
                            except OSError as e:
                                print(f"[Handler] Write error: {e}", file=sys.stderr)
                                break
                        else:
                            # Silently ignore echoed/garbage data
                            pass

        except Exception as e:
            print(f"[Handler] Error: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        finally:
            print(f"[Handler] Cleaning up fd={fd_num}", file=sys.stderr)
            try:
                os.close(fd_num)
            except:
                pass
            if fd_num in self.connections:
                del self.connections[fd_num]


def get_adapter_path(bus):
    """Find the default Bluetooth adapter path."""
    manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, "/"),
        "org.freedesktop.DBus.ObjectManager"
    )

    objects = manager.GetManagedObjects()
    for path, interfaces in objects.items():
        if ADAPTER_INTERFACE in interfaces:
            return path

    raise Exception("No Bluetooth adapter found")


def set_adapter_discoverable(bus, adapter_path):
    """Make the adapter discoverable and pairable."""
    adapter = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path),
        "org.freedesktop.DBus.Properties"
    )

    # Power on
    adapter.Set(ADAPTER_INTERFACE, "Powered", dbus.Boolean(True))

    # Make discoverable (no timeout)
    adapter.Set(ADAPTER_INTERFACE, "Discoverable", dbus.Boolean(True))
    adapter.Set(ADAPTER_INTERFACE, "DiscoverableTimeout", dbus.UInt32(0))

    # Make pairable (no timeout)
    adapter.Set(ADAPTER_INTERFACE, "Pairable", dbus.Boolean(True))
    adapter.Set(ADAPTER_INTERFACE, "PairableTimeout", dbus.UInt32(0))

    # Get adapter address for logging
    addr = adapter.Get(ADAPTER_INTERFACE, "Address")
    name = adapter.Get(ADAPTER_INTERFACE, "Name")

    print(f"[Adapter] {name} ({addr})", file=sys.stderr)
    print(f"[Adapter] Discoverable: Yes, Pairable: Yes", file=sys.stderr)


def register_agent(bus):
    """Register the auto-pairing agent."""
    agent = AutoPairAgent(bus, AGENT_PATH)

    agent_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, "/org/bluez"),
        AGENT_MANAGER_INTERFACE
    )

    # Register with NoInputNoOutput capability for automatic pairing
    agent_manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    agent_manager.RequestDefaultAgent(AGENT_PATH)

    print("[Agent] Registered as default agent (NoInputNoOutput)", file=sys.stderr)
    return agent


def register_profile(bus, simulator):
    """Register the SPP profile."""
    profile = SPPProfile(bus, PROFILE_PATH, simulator)

    profile_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, "/org/bluez"),
        PROFILE_MANAGER_INTERFACE
    )

    # Profile options
    options = {
        "Name": dbus.String("OBD-II Simulator"),
        "Role": dbus.String("server"),
        "Channel": dbus.UInt16(1),
        "AutoConnect": dbus.Boolean(True),
        "RequireAuthentication": dbus.Boolean(False),
        "RequireAuthorization": dbus.Boolean(False),
    }

    profile_manager.RegisterProfile(PROFILE_PATH, SPP_UUID, options)

    print(f"[Profile] Registered SPP (UUID: {SPP_UUID})", file=sys.stderr)
    return profile


def main():
    # Initialize D-Bus main loop integration
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    # Get system bus
    bus = dbus.SystemBus()

    # Find scan data for simulator
    scan_data_path = "/home/claude/obd-gauge/docs/data/obd_scan_20251207_180326.json"
    if not os.path.exists(scan_data_path):
        scan_data_path = None

    # Create OBD simulator
    simulator = OBDSimulator(scan_data_path)

    print("=" * 60, file=sys.stderr)
    print("OBD Simulator - Bluetooth D-Bus RFCOMM Server", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    try:
        # Get adapter and configure
        adapter_path = get_adapter_path(bus)
        print(f"[Setup] Using adapter: {adapter_path}", file=sys.stderr)

        set_adapter_discoverable(bus, adapter_path)

        # Register agent for automatic pairing
        agent = register_agent(bus)

        # Register SPP profile
        profile = register_profile(bus, simulator)

        print("", file=sys.stderr)
        print("Server ready! Waiting for connections...", file=sys.stderr)
        print("On client device, scan for this device and connect.", file=sys.stderr)
        print("Press Ctrl+C to stop.", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        # Run the main loop
        mainloop = GLib.MainLoop()

        def signal_handler(sig, frame):
            print("\n[Main] Shutting down...", file=sys.stderr)
            mainloop.quit()

        # Only exit on SIGINT (Ctrl+C), ignore SIGHUP and SIGTERM for daemon mode
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)  # Ignore hangup

        mainloop.run()

    except dbus.exceptions.DBusException as e:
        print(f"[Error] D-Bus error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[Error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
