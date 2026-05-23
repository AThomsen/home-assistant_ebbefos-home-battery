# Ebbefos/Xolta Home Battery for Home Assistant

**Unofficial integration for Ebbefos Home battery energy platform 🏠🔋☀️**

Uses the existing api of the web app as it seems no public api is available.

This integration is in no way affiliated with Ebbefos Energy A/S.


## Installation

Install integration using HACS: HACS -> Integrations -> (kebab menu) -> Custom repositories -> Repsitory `https://github.com/AThomsen/home-assistant_ebbefos-home-battery` Category: Integration.

During setup, provide a **refresh token** from your browser session. The integration uses it to fetch fresh access tokens automatically and keep the connection alive.

### To get the refresh token
1. Log into https://app.ebbefos.dk/battery
2. Enter *Developer tools* in your browser. Typically done by pressing `F12`.
3. Find *Local storage* for the web app:
    * In Firefox, go to *Storage / Local storage / https://app.effefos.dk*.
    * In Chrome based browsers, go to the *Application* tab, *Storage / Local Storage / https://app.effefos.dk*.
4. Find the key `oidc.user:https://id.ebbefos.dk/:napp` and extract the `refresh_token` value from the json value.


## Example usage

### Power flow card plus

Example of using the integration with the [power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus).

It shows the current flow of power in a card similar to the one in Home Assistant showing todays energy flow.

~~~yaml
type: custom:power-flow-card-plus
entities:
  battery:
    entity: sensor.<replace-with-id>_battery_power_flow
    state_of_charge: sensor.<replace-with-id>_battery_level
  grid:
    entity: sensor.<replace-with-id>_grid_power_flow
    name: Grid
    secondary_info:
      # optional - for use with https://github.com/MTrab/energidataservice
      entity: sensor.elpris
      unit_of_measurement: # currency
      decimals: 2
      display_zero: true
      unit_white_space: false
      color_value: false
  solar:
    entity: sensor.<replace-with-id>_pv_power
    display_zero_state: true
    name: Solar
    use_metadata: false
    color_value: true
  home:
    entity: sensor.<replace-with-id>_power_consumption
clickable_entities: true
use_new_flow_rate_model: true
dashboard_link: /energy
title: Flow
~~~
