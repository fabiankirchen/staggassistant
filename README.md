<img src="icons/icon.png" align="left" width="140" alt="StaggAssistant Logo" style="margin-right: 20px;">

# StaggAssistant 🦢☕️

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/fabiankirchen/staggassistant)](https://github.com/fabiankirchen/staggassistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant integration for the **Fellow Stagg EKG Pro** kettle.
This integration bypasses the need for an official API by communicating directly with the kettle's internal **CLI wrapper** over HTTP.

<br clear="left"/>

## ✨ Features

* **Direct CLI Communication:** Sends commands directly to the device's internal interface (e.g., `ss S_Heat`, `settempr`).
* **Precision Control:** Supports 0.5°C steps for target temperature.
* **Configurable:** Adjust the update interval to your liking (default: 15s).

## 🚀 Installation

### Option 1: HACS (Recommended)

1.  Open HACS in Home Assistant.
2.  Go to **Integrations** > Top right menu (**⋮**) > **Custom repositories**.
3.  Add the URL of this repository: `https://github.com/fabiankirchen/staggassistant`
4.  Category: **Integration**.
5.  Click **Add**, then search for "StaggAssistant" in the list and install it.
6.  Restart Home Assistant.

### Option 2: Manual

1.  Download the latest release from the [Releases section](https://github.com/fabiankirchen/staggassistant/releases).
2.  Unzip the file.
3.  Copy the `staggassistant` folder into your `custom_components` directory (`/config/custom_components/staggassistant`).
4.  Restart Home Assistant.

## ⚙️ Configuration

1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration** in the bottom right corner.
3.  Search for **StaggAssistant**.
4.  Enter the **IP address** of your kettle.

## 🤖 Disclaimer

This integration is purely vibe coded. I’ve got a very limited coding knowledge and therefore cannot guarantee anything. I built this integration for myself, but maybe you can need it. If you can improve it – feel free, I’m happy to help as much as I can.

## ❤️ Credits

Big thanks to **[@tomtastic](https://github.com/tomtastic)** and his project **[stagg-ekg-pro](https://github.com/tomtastic/stagg-ekg-pro)** where I discovered how I can communicate with the kettle.

## 📄 License

MIT License. See [LICENSE](LICENSE) file for more details.
This project is not affiliated with Fellow Industries, Inc.
