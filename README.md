<img src="icon.png" align="top-left" width="140" alt="StaggAssistant Logo" style="margin-right: 20px; padding-bottom: 20px;">

# StaggAssistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/fabiankirchen/staggassistant)](https://github.com/fabiankirchen/staggassistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for the **Fellow Stagg EKG Pro** smart electric kettle.
StaggAssistant communicates 100% locally with the kettle over your LAN (`local_polling`) without any cloud dependency, and optionally uses Bluetooth Low Energy (BLE) for zero-effort IP discovery and automatic DHCP lease updates.

<br clear="left"/>

## ✨ Features

* **Automatic Bluetooth Discovery & Manual BLE/IP Setup:** Automatically discovers `EKG-*` kettles via Home Assistant's Bluetooth integration, reads their current IPv4 address, Wi-Fi MAC, and firmware version from BLE GATT characteristics, and automatically refreshes changed DHCP IPs (`discovery-update-info`).
* **Dual Firmware Architecture (v1.2.26+ & Legacy):** Automatically uses the modern `GET /temp` JSON endpoint on firmware 1.2.26+, caches legacy `/cli` detection to avoid unnecessary 404 requests, periodically re-probes for in-place firmware updates, and robustly sanitizes lifted kettle readings (`NaN`, `-nan`, `null`).
* **Reconfigure, Options & Automatic Repair Flows:** Update the IP address or rediscover via Bluetooth anytime via **Reconfigure** without losing entities or history, adjust polling intervals (5–120s) via **Options**, and resolve prolonged connection drops directly from **Settings > System > Repairs**.
* **Hardware & Fire Safety Interlocks:**
  * **Dry-Boil Guard:** Heating (`HVACMode.HEAT`) is strictly blocked if low water (`no_water` / `S_NoWater`) is detected.
  * **Undocked & Unknown-State Protection:** Heating cannot be started when the kettle is lifted (`is_docked == False`) or telemetry is unavailable (`coordinator.data is None`).
  * **Safe Temperature Adjustments:** Changing target temperature while off never turns on the heater.
  * **Strict Command Allowlist:** Every CLI command is checked against an 18-command safety blocklist and strict `\Z`-anchored regex allowlist, blocking raw GPIO/triac commands (`heaton`, `warmduty`, `htest`, `triactrace`) and destructive wipe commands (`clrsettings`, `wifierase`, `reset`).
  * **Guaranteed Dial Release:** Timer long-press sends `2u` via `asyncio.shield` only after `2d` succeeds.
* **ESP32 & Flash-Wear Protection:** Serializes all HTTP requests through an `asyncio.Lock` with a 150 ms cooldown, sets `PARALLEL_UPDATES` across all platforms, caps streaming responses, disables HTTP redirects (`allow_redirects=False`), and debounces persistent `Store` writes only when settings actually change.
* **Native Entity Hygiene & Full Multilingual Support:** Extended/advanced entities use Home Assistant's native `entity_registry_enabled_default = false` and `EntityCategory` (`CONFIG` / `DIAGNOSTIC`), with complete English and German (`de`) translations, `icons.json`, translated exceptions, and redacted diagnostics.

---

## 📱 Supported Devices & Firmware Matrix

| Device | Firmware | State Endpoint | Settings Read-Back | Controls & Safety |
| :--- | :--- | :--- | :--- | :--- |
| **Fellow Stagg EKG Pro** | **v1.2.26+** | `GET /temp` (JSON) | Restricted by firmware (persisted via local `Store`) | Full climate, sensors, binary sensors, switches, numbers, selects, buttons |
| **Fellow Stagg EKG Pro** | **< v1.2.26 (Legacy)** | `GET /cli?cmd=state` | `GET /cli?cmd=prtsettings` | Full climate, sensors, binary sensors, switches, numbers, selects, buttons |

---

## 📋 Supported Entities & Functions

StaggAssistant exposes **27 entities** across **7 platforms** (`climate`, `sensor`, `binary_sensor`, `button`, `switch`, `number`, `select`):

| Platform | Entity (EN) | Entity (DE) | Category | Default Enabled | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`climate`** | Kettle | Wasserkocher | Primary | ✅ Yes | Main thermostat UI to turn heating on/off and set target temperature (40–100 °C) |
| **`sensor`** | Current temperature | Aktuelle Temperatur | Primary | ✅ Yes | Current water temperature (`measurement` state class for long-term statistics) |
| **`sensor`** | Target temperature | Zieltemperatur | Primary | ✅ Yes | Active target temperature |
| **`sensor`** | State mode | Betriebszustand | Primary | ✅ Yes | Enum state (`off`, `standby`, `heat`, `heating_to_target`, `pre_boil`, `hold`, `low_water`, `fail`, `ota`) |
| **`sensor`** | Clock time | Uhrzeit | Diagnostic | ✅ Yes | Kettle's current clock time |
| **`sensor`** | Boil temperature | Siedetemperatur | Diagnostic | ❌ Disabled | Altitude-adjusted boiling temperature |
| **`sensor`** | Schedule time | Zeitplan-Uhrzeit | Diagnostic | ❌ Disabled | Cached wake-up schedule time (`HH:MM`) |
| **`sensor`** | Schedule temperature | Zeitplan-Temperatur | Diagnostic | ❌ Disabled | Cached wake-up schedule target temperature |
| **`binary_sensor`** | Docked | Auf Basis | Primary | ✅ Yes | `connectivity` sensor indicating whether the kettle sits on its base |
| **`binary_sensor`** | Low water warning | Niedrigwasser-Warnung | Primary | ✅ Yes | `problem` dry-boil / low-water alert (`nw` flag / `S_NoWater`) |
| **`binary_sensor`** | Target temperature reached | Zieltemperatur erreicht | Primary | ✅ Yes | Indicates water has reached target temperature |
| **`binary_sensor`** | Heating active | Heizen aktiv | Primary | ✅ Yes | `heat` sensor active during heating, startup, and pre-boil |
| **`binary_sensor`** | Hold active | Warmhalten aktiv | Primary | ✅ Yes | Active while keep-warm hold mode is running |
| **`binary_sensor`** | Pre-boil active | Pre-Boil aktiv | Primary | ❌ Disabled | Indicates pre-boil phase is running |
| **`button`** | Start timer | Brühtimer starten | Primary | ✅ Yes | Long-presses main dial (`2d` → 2s → `2u`) to start brew timer |
| **`button`** | Press main button | Haupttaster drücken | Config | ✅ Yes | Simulates short dial press (`2`) |
| **`button`** | Press menu button | Menütaste drücken | Config | ✅ Yes | Simulates back/menu press (`1`) |
| **`button`** | Rotate dial left | Drehknopf links drehen | Config | ✅ Yes | Simulates counter-clockwise dial rotation (`q`) |
| **`button`** | Rotate dial right | Drehknopf rechts drehen | Config | ✅ Yes | Simulates clockwise dial rotation (`w`) |
| **`button`** | Sync time | Uhrzeit synchronisieren | Config | ✅ Yes | Synchronizes Home Assistant local time to kettle (`setclock`) |
| **`button`** | Reload data | Daten neu laden | Diagnostic | ✅ Yes | Triggers an immediate coordinator refresh |
| **`switch`** | Pre-boil | Pre-Boil | Config | ❌ Disabled | Toggles pre-boil feature on/off |
| **`number`** | Hold time duration | Warmhaltezeit | Config | ❌ Disabled | Keep-warm duration in minutes (0–60) |
| **`number`** | Altitude setting | Höheneinstellung | Config | ❌ Disabled | Elevation in meters (0–3000) for boil calibration |
| **`number`** | Chime volume | Signalton-Lautstärke | Config | ❌ Disabled | Chime speaker volume (0–10) |
| **`number`** | Schedule temperature | Zeitplan-Temperatur | Config | ❌ Disabled | Scheduled target temperature (40–100 °C) |
| **`select`** | Clock style | Uhrenstil | Config | ❌ Disabled | Display clock mode (`off`, `digital`, `analog`) |
| **`select`** | Language selection | Sprachauswahl | Config | ❌ Disabled | Kettle display language (`en`, `fr`, `es`, `zh-Hans`, `zh-Hant`, `ko`, `ja`) |
| **`select`** | Temperature units | Temperatureinheit | Config | ❌ Disabled | Display unit (`C`, `F`) |
| **`select`** | Schedule mode | Zeitplan-Modus | Config | ❌ Disabled | Schedule mode (`off`, `once`, `repeat`) |

> **Tip:** To enable any disabled-by-default entity, open **Settings > Devices & Services > StaggAssistant > [Your Kettle]**, click the entity in the **Entities** list, and toggle **Enabled**.

---

## 🚀 Installation

### Prerequisites
* Home Assistant **2024.12.0** or newer.
* Your Stagg EKG Pro must be connected to the same local network (no guest isolation blocking local HTTP port 80).
* *(Optional for BLE discovery)* Home Assistant's **Bluetooth** integration and an active local adapter or ESPHome Bluetooth Proxy in range of the kettle.

### Option 1: HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Go to **Integrations** > Top-right menu (**⋮**) > **Custom repositories**.
3. Add `https://github.com/fabiankirchen/staggassistant` with category **Integration**.
4. Search for **StaggAssistant** and click **Download**.
5. Restart Home Assistant.

### Option 2: Manual
1. Download the latest release from the [Releases section](https://github.com/fabiankirchen/staggassistant/releases).
2. Extract and copy `custom_components/staggassistant` into your Home Assistant `/config/custom_components/` directory.
3. Restart Home Assistant.

### 🧪 Bleeding-Edge Beta Channel (Optional)
If you want to test experimental features before human hardware verification and merge into this repository, you can track the development fork `https://github.com/fabiagent/staggassistant` in HACS (category: **Integration**).

---

## ⚙️ Setup, Configuration & Reconfiguration

### Initial Setup (`Add Integration`)
If Home Assistant detects your kettle via Bluetooth (`EKG-*`), it appears automatically under **Settings > Devices & Services** for one-click confirmation. Otherwise:
1. Go to **Settings > Devices & Services > Add Integration** and search for **StaggAssistant**.
2. Choose either **Scan for kettle (Bluetooth)** or **Enter IP address manually**.

#### Installation Parameters
| Parameter | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `ip_address` | Yes (manual) | — | Local IPv4 address (excluding loopback/multicast/reserved) or local hostname (e.g., `kettle.local`, without `http://` or port). |
| `ble_address` | Yes (BLE) | — | Discovered `EKG-*` Bluetooth device address. |
| `name` | No | `"Stagg Kettle"` / BLE name | Friendly device name in Home Assistant. |
| `scan_interval` | No | `15` | Polling interval in seconds (`5–120`). |

### Post-Setup Configuration (`Options`, `Reconfigure` & `Repairs`)
* **Options (`Configure`):** Adjust `scan_interval` (`5–120` seconds) without reloading or interrupting entities.
* **Reconfigure (`⋮` → `Reconfigure`):** Update the kettle's IP address manually or rediscover it over Bluetooth while preserving all entity IDs, device identifiers, and history.
* **Automatic Repair Issues:** If the kettle cannot be reached for 5 consecutive polling cycles, StaggAssistant creates an actionable repair issue under **Settings > System > Repairs** allowing you to enter the new IP directly. The issue clears automatically once the kettle becomes reachable again.

---

## 📊 Data Update & ESP32 Protection

* **Polling Strategy:** Uses a `DataUpdateCoordinator` polling every `15` seconds by default (`5–120`s configurable).
* **ESP32 Protection:** Every HTTP call is serialized through an `asyncio.Lock` with a 150 ms inter-request cooldown, 6s/10s strict timeouts, `PARALLEL_UPDATES = 1` on write platforms (`0` on read-only sensor platforms), and no `allow_redirects`.
* **Storage Efficiency:** Cached settings are saved to `.storage/staggassistant_<stable_id>` via `Store.async_delay_save(..., 5.0)` **only** when persistent values change (volatile `clock_time` is never written to disk). Removing the integration cleans up all stored files and open repair issues.

---

## 🤖 Use Cases & Automation Examples

### 1. Morning Coffee Boil Automation
```yaml
alias: "Morning Stagg Boil"
description: "Heat kettle to 94 °C on weekday mornings"
mode: single
triggers:
  - trigger: time
    at: "07:00:00"
conditions:
  - condition: state
    entity_id: binary_sensor.stagg_kettle_docked
    state: "on"
  - condition: state
    entity_id: binary_sensor.stagg_kettle_low_water_warning
    state: "off"
actions:
  - action: climate.set_temperature
    target:
      entity_id: climate.stagg_kettle
    data:
      temperature: 94
  - action: climate.set_hvac_mode
    target:
      entity_id: climate.stagg_kettle
    data:
      hvac_mode: heat
```

### 2. Notify When Water Reaches Target Temperature
```yaml
alias: "Kettle Ready Notification"
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.stagg_kettle_target_temperature_reached
    from: "off"
    to: "on"
actions:
  - action: notify.persistent_notification
    data:
      title: "Coffee Time!"
      message: "Your Fellow Stagg EKG Pro has reached {{ states('sensor.stagg_kettle_current_temperature') }} °C."
```

### 3. Low-Water Safety Alert
```yaml
alias: "Kettle Low Water Warning"
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.stagg_kettle_low_water_warning
    to: "on"
actions:
  - action: notify.persistent_notification
    data:
      title: "Refill Kettle"
      message: "Stagg EKG Pro reported low water; heating is blocked."
```

---

## ⚠️ Known Limitations

* **Firmware 1.2.26+ Settings Read-Back:** Fellow disabled textual output on `/cli?cmd=prtsettings` starting with v1.2.26. Extended settings still work as write commands and persist across Home Assistant restarts via local caching, but changes made physically on the kettle dial are not reflected back to Home Assistant on v1.2.26+.
* **Single Local HTTP Stack:** The kettle's embedded ESP32 web server handles connections sequentially. Very short polling intervals combined with simultaneous external HTTP clients may cause transient timeouts.
* **ARP Fallback Scope:** If BLE GATT characteristic `c4b4` cannot be read during Bluetooth resolution, ARP table matching requires Home Assistant to share the same Layer-2 broadcast domain (host networking).

---

## 🔍 Troubleshooting & Debug Logging

1. **Kettle unreachable after router/DHCP change:** Use **Settings > Devices & Services > StaggAssistant > `⋮` > Reconfigure** (or accept the automatic **Repairs** prompt) to enter the new IP or rediscover via Bluetooth.
2. **Kettle shows "Unavailable" when unplugged or Wi-Fi drops:** Expected behavior. Home Assistant logs once when connectivity drops and once when it recovers.
3. **Enable Debug Logging:** Add the following to `configuration.yaml` and restart Home Assistant:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.staggassistant: debug
   ```
4. **Download Diagnostics:** Go to **Settings > Devices & Services > StaggAssistant > `⋮` > Download diagnostics**. Sensitive fields (`ip_address`, `wifi_mac`, `ble_address`, `device_id`, `name`, `title`, `unique_id`, `ssid`) are automatically redacted before export.

---

## 🗑️ Removal Instructions

1. Go to **Settings > Devices & Services**.
2. Open **StaggAssistant**, click the three-dot menu (**⋮**) on the integration entry, and select **Delete**. (Persisted `.storage` cache files and repair issues are removed automatically.)
3. If installed via **HACS**, go to **HACS > Integrations**, click **⋮** on **StaggAssistant**, and choose **Remove**.
4. Restart Home Assistant.

---

## 🤖 AI Co-Maintenance & Development

This repository is maintained by [@fabiankirchen](https://github.com/fabiankirchen) in collaboration with **`fabiagent`** (autonomous coding agent).
* **Stable Upstream (Recommended):** [`fabiankirchen/staggassistant`](https://github.com/fabiankirchen/staggassistant) — **100% human-verified:** Every release and code change in this main repository is thoroughly tested on real physical kettle hardware by Fabian Kirchen before being merged and published.
* **Development Fork (Bleeding-Edge):** [`fabiagent/staggassistant`](https://github.com/fabiagent/staggassistant) — Rapid autonomous iterations, automated test builds, and pre-releases for early testers before human hardware verification.

---

## ❤️ Credits

* Repository owner: **[@fabiankirchen](https://github.com/fabiankirchen)**
* Huge thanks to **[@tomtastic](https://github.com/tomtastic)** for his reverse-engineering and comprehensive [Firmware 1.2.26 analysis](https://github.com/tomtastic/homebridge-stagg-ekg-pro/wiki/1.2.26) of the Stagg EKG Pro ESP32 image.
* Big thanks to the repositories **[stagg-ekg-pro](https://github.com/tomtastic/stagg-ekg-pro)** & **[homebridge-kettle](https://github.com/Willmac16/homebridge-kettle/tree/ekg-pro-cli)** through which direct kettle CLI communication was discovered.
* A huge shout-out and massive thanks to **[@miguelcaravantes](https://github.com/miguelcaravantes)** for contributing the multi-platform overhaul, unlocking the scheduling features, dial buttons, and lifting this integration to a whole new level!

---

## 📄 License

MIT License. See [LICENSE](LICENSE) file for more details.
This project is an independent community project and is not affiliated with Fellow Industries, Inc.
