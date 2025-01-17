# Home Assistant Fiat/Chrysler/Dodge/Jeep/Ram integration

This integration is using the Fiat Uconnect cloud API which was reverse-engineered from the native app traffic capture & its decompilation.

## Requirements
* A supported car made by one of Stellantis brands
* Uconnect (or whatever it is called for other brands) subscription activated

## Features
* Get current car state periodically
* Send commands to the car:
  - Initiate charging
  - Enable air conditioning
  - Update location
  - ...etc

Be advised that I only tested it a Fiat 500e in Europe, so please open issues if there are problems with other cars/brands/regions.

## Setting up
* Install the integration through HACS
* Add it and input your email/password and optionally PIN.
  PIN is needed if you want to execute remote commands.
* Select your brand + region combo

## Caveats
* The API sometimes is slow or non-working. The states are also not updated frequently sometimes. For example to update the battey SOC during charge you can set up an automation that would call `deep_refresh` service periodically if the car is plugged in.
* Commands outcome is not yet checked since I don't see an available API for it besides the notifications, will try to implement that later.

## Example
![Dashboard](dashboard.png)
