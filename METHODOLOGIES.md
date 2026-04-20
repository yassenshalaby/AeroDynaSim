# AeroDynaSim — Methodologies Report

## 1. Introduction

This report outlines the methodology followed in the development of **AeroDynaSim**, a desktop web application that lets users customise the geometric shape of a car and immediately see how those changes affect its lap time on a real racing circuit. The project brings together a publicly available aerodynamic dataset (DrivAerNet), a physics-based lap time simulator, and a user-facing interface built with Flask and vanilla JavaScript. The aim was to make aerodynamic design decisions tangible and interactive rather than something that only happens inside CFD software.

## 2. Research and Data Selection

### 2.1 The DrivAerNet Dataset

The starting point for the project was choosing a reliable source of aerodynamic data. After looking at what was available, the DrivAerNet parametric dataset was selected. It contains 8,150 unique car body designs generated from 23 geometric parameters — things like car length, roof height, trunk lid angle, mirror position, and so on. Each design in the dataset comes with pre-computed aerodynamic coefficients (drag coefficient Cd, front lift coefficient Cl_f, and rear lift coefficient Cl_r), which were originally obtained through computational fluid dynamics simulations.

What made this dataset particularly suitable was that it covers three distinct body types — Sedan (Notchback), Wagon (Estate), and Fastback — which gave users a meaningful starting point to work from. The parameters are also physically intuitive: adjusting "trunk lid angle" or "door handle position" is something anyone can understand, unlike directly editing drag coefficients.

### 2.2 Lap Time Simulation Engine

For the simulation side, an existing open-source lap time simulator was used. This simulator takes in a vehicle configuration (mass, power, tyre data, aerodynamic coefficients) and a track layout, then calculates the fastest possible lap time by solving the longitudinal and lateral dynamics at every point around the circuit. It accounts for:

- Aerodynamic drag and downforce forces at each speed
- Tyre grip limits under braking, acceleration, and cornering
- Engine power and torque delivery
- Energy consumption and management

The simulator works by dividing the track into small segments (roughly every 5 metres) and computing the maximum possible speed at each one, considering both the car's mechanical grip and the aerodynamic forces acting on it. The result is a complete velocity profile around the lap.

Twenty-four real-world circuit layouts are included (Shanghai, Monza, Spa, Silverstone, and many more), taken from publicly available raceline data.

## 3. System Architecture

### 3.1 Overall Design

The application follows a straightforward client-server architecture:

- **Backend** — A Python Flask server handles data loading, parameter processing, and simulation execution.
- **Frontend** — A single-page HTML/CSS/JavaScript interface provides the user experience.
- **Desktop Wrapper** — The app is launched as a native desktop window using PyWebView, so it feels like a standalone application rather than something running in a browser.

This approach was chosen because it keeps everything self-contained. The user doesn't need to set up a database, run Docker containers, or configure anything. They just launch the app and the Flask server starts in the background while a native window opens.

### 3.2 Data Flow

The data flows through the system in a series of clear steps:

1. **User selects a body type** (Sedan, Wagon, or Fastback) → the backend loads the default geometric parameters for a representative design from the DrivAerNet CSV.
2. **User adjusts geometric parameters** using sliders in the UI → the frontend stores these values locally.
3. **User saves one or more presets** → each preset captures a snapshot of all 23 parameter values.
4. **User picks a track and runs the simulation** → the frontend sends all presets to the backend in a single API call.
5. **Backend finds the closest matching design** in the DrivAerNet database for each preset, retrieves its Cd/Cl values, converts them into the simulator's format, generates a temporary vehicle configuration file, and runs the lap time solver.
6. **Results come back** with lap times, speed profiles, and rankings, which the frontend renders as a table and an interactive track visualisation.

## 4. Nearest-Neighbour Matching

One of the key methodological decisions was how to go from user-adjusted geometric parameters back to valid aerodynamic coefficients. Rather than trying to build a predictive model (which would have added significant complexity and potential error), the approach taken was a **nearest-neighbour lookup** against the full DrivAerNet database.

When the user submits their custom parameters, the backend calculates the Euclidean distance in normalised parameter space between the user's configuration and every design in the dataset. Each parameter is normalised by dividing the difference by a fixed scaling factor (100 mm for length-based parameters, which roughly captures their typical range). The design with the smallest overall distance is selected, and its pre-computed Cd, Cl_f, and Cl_r values are used for the simulation.

This method has a few advantages:
- It guarantees that the aerodynamic coefficients used are physically realistic, because they come from actual CFD results.
- It avoids the risk of extrapolation errors that a regression model might introduce for extreme parameter combinations.
- It's straightforward to implement and easy to reason about.

The trade-off is that if the user sets parameters to something very different from any design in the dataset, the matched design might not perfectly represent what they intended. However, with 8,150 designs covering a wide range of the parameter space, this was considered an acceptable compromise for this project.

## 5. Aerodynamic-to-Simulator Conversion

Once the nearest design is found, its aerodynamic coefficients need to be translated into the format the lap time simulator expects. The simulator works with aerodynamic "areas" rather than raw coefficients, so the conversion is:

- **Drag area** (c_w_a) = Cd × frontal area
- **Front downforce area** (c_z_a_f) = |Cl_f| × frontal area (only if Cl_f indicates downforce)
- **Rear downforce area** (c_z_a_r) = |Cl_r| × frontal area (only if Cl_r indicates downforce)

A typical sedan frontal area of 2.16 m² was used across all body types to keep comparisons consistent. This is a simplification — in reality, wagons and fastbacks would have slightly different frontal areas — but it ensures that any differences in lap time are driven by shape changes rather than size changes, which aligns better with the project's focus on aerodynamic design.

The base mechanical properties (mass, engine power, tyre characteristics) come from the simulator's built-in vehicle template. These are kept constant across all simulations so that the only variable is the aerodynamics. This isolates the effect of the user's design choices.

## 6. Frontend Development

### 6.1 Interface Design

The user interface went through two major iterations:

- **Version 1** used a step-by-step wizard (Step 1 → 2 → 3 → 4) that forced users through a linear flow. This was straightforward but inflexible — users couldn't easily go back and tweak parameters after seeing their results.
- **Version 2** replaced this with a **tab-based navigation** system. Four tabs (Body Type, Customise, Track, Results) are always accessible, letting users jump between sections freely. This was a deliberate design choice to support an iterative workflow: adjust parameters, simulate, check results, go back and adjust again.

The 23 geometric parameters are organised into five collapsible groups (Body, Exterior, Windows, Mirrors, Details) to avoid overwhelming the user with a wall of sliders. Each slider shows its current value in real units (millimetres or degrees), and a "Reset to Stock" button lets users quickly return to the default configuration.

### 6.2 Preset System

A preset system was implemented so users can save multiple configurations and compare them head-to-head. The "Stock" preset (the unmodified body type defaults) is always included as a baseline. Users can save as many custom presets as they like, and the simulation runs all of them in a single batch against the selected track.

This comparative approach is central to the application's purpose. Rather than just showing a single lap time, it always shows how the user's modifications compare to the stock car and to each other, including exact time deltas and improvement indicators.

### 6.3 Track Visualisation

After simulation, the results include a 2D track map with a colour-coded speed overlay. Red sections indicate low speed (heavy braking zones or tight corners), yellow is mid-range, and green is high speed (straights and fast sweepers). This gives users a visual understanding of where their aerodynamic changes have the most impact — for example, a low-drag setup might show more green on the straights but more red in the corners compared to a high-downforce configuration.

The track coordinates are loaded from CSV files containing raceline data, and the visualisation is rendered on an HTML5 Canvas element with device-pixel-ratio scaling for sharp rendering on high-DPI displays.

## 7. Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | Python 3 + Flask | Simple to set up, well-suited for serving APIs and running simulation code |
| Simulation | laptimesim (Python) | Open-source, physics-based, supports multiple tracks |
| Dataset | DrivAerNet CSV (8,150 designs) | Comprehensive parametric car dataset with CFD-validated aero coefficients |
| Frontend | HTML5 + CSS3 + vanilla JavaScript | No build tools or framework dependencies, keeps things lightweight |
| Desktop wrapper | PyWebView | Wraps the web app in a native OS window |
| Fonts | Google Fonts (Orbitron + Inter) | Orbitron for the header branding, Inter for readable body text |

## 8. Testing and Validation

Testing was done in a practical, hands-on way rather than through automated test suites:

- **Data integrity** was verified by checking that the DrivAerNet CSV loaded correctly and that representative designs for all three body types could be found and parsed.
- **Nearest-neighbour accuracy** was checked by running searches with known parameter sets and confirming that the expected design was returned.
- **Simulation consistency** was validated by running the same configuration multiple times and confirming identical results (the simulator is deterministic).
- **End-to-end workflow** was tested by selecting each body type, adjusting parameters, saving presets, choosing different tracks, and running simulations to make sure the full pipeline produced reasonable lap times.
- **UI responsiveness** was verified by navigating between tabs, saving and loading presets, and confirming that parameter values persisted correctly across the interface.

Typical lap times on the Shanghai circuit fell in the range of roughly 1:35 to 1:45, which is plausible given the vehicle parameters and track length. Changing aerodynamic parameters produced time differences of tenths to full seconds, consistent with what would be expected from real-world aerodynamic modifications.

## 9. Limitations and Future Work

A few limitations are worth noting:

- **No real-time CFD** — The app uses pre-computed aerodynamic data via nearest-neighbour lookup rather than running actual CFD for custom shapes. This means the aerodynamic response to every possible parameter combination isn't perfectly captured, just approximated by the closest existing design.
- **Fixed frontal area** — Using a constant 2.16 m² frontal area across all body types is a simplification. Ideally each body type would have its own measured frontal area.
- **No SUV body type** — The DrivAerNet dataset only includes Sedan, Wagon, and Fastback. An SUV or crossover category would broaden the appeal but would require additional data.
- **Parameter range estimation** — The slider ranges in the UI are estimated at ±50% of the stock value, which works reasonably well but could be more precisely calibrated to the actual dataset ranges for each body type.

Possible future improvements would include training a lightweight regression model (for example, a neural network) on the DrivAerNet data to predict Cd/Cl from arbitrary parameter combinations, adding 3D visualisation of the car shape, and implementing real-time parameter sensitivity analysis to show which parameters have the biggest effect on lap time.

## 10. Conclusion

The methodology followed in this project prioritised practicality and accessibility. By combining an established aerodynamic dataset with a physics-based simulator and wrapping it all in an interactive desktop application, the result is a tool that makes aerodynamic design exploration genuinely approachable. Users can tweak real car features — roof height, trunk angle, mirror position — and immediately see the downstream effect on lap performance, bridging the gap between abstract aerodynamic theory and tangible design decisions.
