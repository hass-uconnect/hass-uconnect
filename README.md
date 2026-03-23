![logo](logo.png)

Connect your Uconnect-enabled vehicle to Home Assistant. This integration has been made from the reverse-engineered Stellantis vehicle-branded apps and websites.

## Car Brands

US, Canada, EU & Asia regions are supported. Try a different region if the originally selected region does not authenticate.

- Abarth: Works ✅
- Alfa Romeo: Works ✅
- Chrysler: Unknown ❔
- Dodge: Unknown ❔
- Fiat: Works ✅
- Jeep: Works ✅
- Maserati: Unknown ❔
- Ram: Works ✅

## Tested Vehicles

- See tested and working vehicles at the following discussion post: https://github.com/hass-uconnect/hass-uconnect/discussions/5
- If your vehicle works, feel free to upload the year, make and model to the discussion post.

## Prerequisites 📃

- Home Assistant
- [HACS](https://www.hacs.xyz) (Home Assistant Community Store) 
- A vehicle using Uconnect cellular services, **vehicles that use [SiriusXM Guardian](https://www.driveuconnect.com/sirius-xm-guardian/siriusxm-guardian-modal.html) are not supported**
- Check the links below:
  - Alfa Romeo: https://connect.alfaromeo.com
  - Chrysler: https://connect.chrysler.com
  - Dodge: https://connect.dodge.com
  - Fiat: https://connect.fiat.com
  - Jeep: https://connect.jeep.com
  - Maserati: https://connect.maserati.com
  - Ram: https://connect.ramtrucks.com

## Features ✔️

- Imports statistics like battery level 🔋, tire pressure ‍💨, odometer ⏲ etc. into Home Assistant
- **Extrapolated Battery**: For EVs, provides a real-time battery estimate between API updates by tracking charging rate and idle drain. Automatically rejects stale data that would show impossible values (e.g., battery dropping while charging), and correctly handles state transitions (e.g., idle to charging, charging to driving). Triggers an automatic deep refresh when charging starts after idle to get fresh SOC data. Preserves the charging rate across sessions so that extrapolation begins immediately when a new charging session starts, even before time-to-full data is available from the API
- **Charging Rate**: Shows the current charging speed in %/hour. Computed over a 60-minute sliding window of SOC readings for stable output even with integer SOC values and irregular polling. Falls back to a time-to-full estimate during the first hour of a session
- **Reset Battery Learning**: Button to reset the learned charging correction factor and idle drain rate back to defaults. Useful when changing chargers or if learned values have drifted
- Multiple Brands: Abarth, Alfa Romeo, Chrysler, Dodge, Fiat, Jeep, Maserati & Ram
- Multiple Regions: America, Canada, Europe & Asia
- Supports multiple cars on the same account 🚙🚗🚕
- Location tracking 🌍
- Live vehicle status such as windows/doors, and ignition status for supported vehicles
- Home Assistant zones (home 🏠, work 🏦 etc.) support
- Uses the same data source as the official app 📱
- Remote commands (unlock doors 🚪, switch HVAC 🧊 on , ...). **Use a service (action) to trigger commands**. Some commands may not work with all vehicles
- Available commands are:
  - `Refresh Location`: Updates the vehicle location
  - `Deep Refresh`: Refreshes EV battery level
  - `Lights/Horn`: Trigger vehicle horn and lights
  - `Lights`: Trigger vehicle lights
  - `Preconditioning On/Off`: Toggle vehicle preconditioning
  - `Trunk Lock/Unlock` / `Liftgate Lock/Unlock`: Lock/Unlock trunk/liftgate
  - `Doors Lock/Unlock`: Lock/Unlock vehicle doors
  - `Engine On/Off`: Remotely starts/stops the vehicle engine
  - `Charge Now`: Initiates EV charging
  - `HVAC On/Off`: Toggles the HVAC
  - `Comfort On/Off`: Another alternative to the above HVAC commands (depends on make/model)
  - `Update`: Asks the integration to update the data from the API immediately

## What will NEVER work? ❌

- Things the Uconnect API does not support such as real time tracking or adjusting the audio volume.
- Some commands are vehicle specific and do not work across all makes and models.
- Some vehicles do not support live status for locks/windows/ignition. 

## How to install 🛠️

- Make sure you have [HACS](https://hacs.xyz/docs/use/#getting-started-with-hacs) already installed
- Add the [repository URL](https://github.com/hass-uconnect/hass-uconnect) to your HACS custom repositories as type `integration`
- Install the integration and restart Home Assistant
- Go to your integrations configuration page once started and add the Uconnect integration
- Fill e-mail, password and optionally PIN if you want to issue commands

After the integration is initialized - you might want to go into its options and enable the creation of command entities:

![image](https://github.com/user-attachments/assets/587c9ec0-bbd0-4918-b84b-4235316a58cf)

## Example dashboard

![image](https://github.com/user-attachments/assets/ceaa1133-be82-4506-a915-7e7c50fb58b6)

## Useful Resources

Cards: 
  - [Ultra Vehicle Card](https://github.com/WJDDesigns/Ultra-Vehicle-Card)
  - [Vehicle Status Card](https://github.com/ngocjohn/vehicle-status-card)
