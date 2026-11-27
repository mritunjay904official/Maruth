import os
import nengo
import numpy as np
from weather_api import get_live_air_quality


def _configure_nengo_cache():
    """Ensure Nengo decoder cache works in restricted or sandboxed environments."""
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nengo_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        nengo.rc.set("decoder_cache", "path", cache_dir)
    except OSError:
        nengo.rc.set("decoder_cache", "enabled", "false")


def run_drosophila_brain(lat=23.67, lon=87.68, air_data=None, return_trace=False):
    """Run the 10-neuron Nengo Drosophila olfactory simulation on live PM2.5 data."""
    _configure_nengo_cache()

    if air_data is None:
        air_data = get_live_air_quality(lat=lat, lon=lon)
    if not air_data:
        return {"error": "Failed to fetch live air quality data"}

    # Scale PM2.5 (0-500) to (0.0-1.0) for the neuron ensemble
    live_pm25 = float(air_data.get("pm2_5", 0.0))
    signal_value = min(max(live_pm25 / 500.0, 0.0), 1.0)

    net = nengo.Network(label="Drosophila Olfactory Sensor")

    with net:
        # Replaced np.sin(...) with live PM2.5 signal
        inp = nengo.Node(output=signal_value)

        ens = nengo.Ensemble(n_neurons=10, dimensions=1)

        nengo.Connection(inp, ens)

        inp_probe = nengo.Probe(inp)
        ens_probe = nengo.Probe(ens, synapse=0.01)
        spike_probe = nengo.Probe(ens.neurons) if return_trace else None

    with nengo.Simulator(net, progress_bar=False) as sim:
        sim.run(5.0)

    print("Input signal and probes added successfully")

    # Extract final neural output from ens_probe
    neural_output = float(np.mean(sim.data[ens_probe][-100:]))
    detected_pm25 = round(neural_output * 500.0, 2)

    result = {
        "live_pm2_5": live_pm25,
        "neural_response": round(neural_output, 4),
        "detected_pm2_5": detected_pm25,
        "status": "HIGH POLLUTION" if detected_pm25 > 100 else "NORMAL",
    }

    if return_trace:
        t_vals = sim.trange()
        step = max(1, len(t_vals) // 60)
        spikes = sim.data[spike_probe]
        dt = sim.dt
        neuron_rates_hz = [round(float(np.mean(spikes[:, idx] > 0) / dt), 1) for idx in range(spikes.shape[1])]
        result["trace"] = {
            "time_s": [round(float(v), 2) for v in t_vals[::step]],
            "input_signal": [round(float(v[0]), 4) for v in sim.data[inp_probe][::step]],
            "neural_signal": [round(float(v[0]), 4) for v in sim.data[ens_probe][::step]],
            "neuron_rates_hz": neuron_rates_hz,
            "mean_firing_rate_hz": round(float(np.mean(neuron_rates_hz)), 1),
        }

    return result


if __name__ == "__main__":
    print(run_drosophila_brain())
