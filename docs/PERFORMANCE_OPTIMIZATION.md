# OBD Gauge Performance Optimization

## Overview

This document captures learnings from analyzing the aa-torque Android Auto gauge app to understand how professional implementations achieve smooth, responsive gauge animations. Key insights apply to our Python/pygame implementation.

## aa-torque Analysis (2025-12-10)

**Repository**: https://github.com/agronick/aa-torque

aa-torque displays Torque Pro OBD data on Android Auto. It uses the SpeedViewLib library for gauge rendering, which provides insights into smooth animation techniques.

### Key Findings

#### 1. Animation Duration = Refresh Interval

**Critical Insight**: The animation duration should match the data refresh rate.

```kotlin
// TorqueGauge.kt:272
private fun onUpdate(data: TorqueData) {
    val fVal = data.lastData.toFloat()
    // Animation duration (300ms) = refresh interval (300ms)
    mClock.speedTo(fVal, TorqueRefresher.REFRESH_INTERVAL)
    mRayClock.speedTo(fVal, TorqueRefresher.REFRESH_INTERVAL)
}
```

**Why it works**: If data arrives every 300ms and needle animation takes 300ms, the needle is always moving toward the latest value. It creates continuous, seamless motion without pauses or jerks.

**Our equivalent**: If polling at 10Hz (100ms intervals), animation should take ~100ms. Current smoothing factor of 0.25 approximates this but could be tuned.

#### 2. DecelerateInterpolator (Fast Start, Slow Finish)

SpeedViewLib uses `DecelerateInterpolator` for needle animation:

```kotlin
// SpeedViewLib Gauge.kt
fun speedTo(speed: Float, moveDuration: Long = 2000) {
    speedAnimator = ValueAnimator.ofFloat(currentSpeed, newSpeed).apply {
        interpolator = DecelerateInterpolator()  // Key!
        duration = moveDuration
        addUpdateListener { animation ->
            currentSpeed = animation.animatedValue as Float
            postInvalidate()
        }
    }
    speedAnimator?.start()
}
```

**Why it works**:
- **Fast start**: Needle responds immediately, feels responsive
- **Slow finish**: Smooth settling, no overshoot
- Better than linear interpolation (feels sluggish) or acceleration-deceleration (feels bouncy)

**Math**: DecelerateInterpolator uses `t = 1 - (1 - t)^2` curve.

**Our pygame equivalent**:
```python
# Current: linear smoothing
self.current_psi += (self.target_psi - self.current_psi) * self.smoothing

# Decelerate-style: would need to track animation progress
# t = time_since_update / animation_duration
# progress = 1 - (1 - t)^2
# self.current_psi = start_psi + (target_psi - start_psi) * progress
```

#### 3. Staggered Polling Offsets

aa-torque staggers each gauge's polling to prevent all gauges from querying OBD simultaneously:

```kotlin
// TorqueRefresher.kt
suspend fun makeExecutors(service: TorqueService) {
    data.values.forEachIndexed { index, torqueData ->
        // Stagger each gauge's refresh offset
        val refreshOffset = (REFRESH_INTERVAL / data.size) * index
        torqueData.refreshTimer = executor.scheduleWithFixedDelay({
            doRefresh(service, torqueData)
        }, refreshOffset, REFRESH_INTERVAL, TimeUnit.MILLISECONDS)
    }
}
```

**Why it works**: With 3 gauges at 300ms intervals:
- Gauge 1 polls at t=0, 300, 600, ...
- Gauge 2 polls at t=100, 400, 700, ...
- Gauge 3 polls at t=200, 500, 800, ...

Each gauge gets updates ~3 times/second, and updates are spread evenly across time.

**Our implementation**: `query_fast()` already rotates through PIDs, achieving similar effect.

#### 4. Refresh Rate: 300ms (3.33 Hz per gauge)

```kotlin
companion object {
    const val REFRESH_INTERVAL = 300L  // 300ms
}
```

This is slower than our target but creates smooth animations. The key is consistency, not raw speed.

## Current Implementation vs aa-torque

| Aspect | aa-torque | Our Implementation |
|--------|-----------|-------------------|
| Refresh rate | 300ms (3.33 Hz) | ~100ms (10 Hz) |
| Animation duration | 300ms (matches refresh) | Variable (smoothing factor) |
| Interpolation | DecelerateInterpolator | Linear smoothing |
| Polling pattern | Staggered per gauge | Rotating single PID |
| Update callback | Direct to gauge | Via callback system |

## Remaining Latency Sources

Even after optimization, ~100-300ms delay is expected due to:

### 1. Bluetooth SPP Latency (~30-80ms)
- Bluetooth serial profile has inherent buffering
- Can't be reduced without different hardware (USB OBD adapter)

### 2. ELM327 Processing (~30-50ms)
- Adapter processes AT commands and OBD queries
- Faster adapters (STN series) may reduce this

### 3. CAN Bus Response (~5-20ms)
- ECU response time varies by PID
- RS7's 500kbps CAN is fast; no improvement possible

### 4. Python/pygame Rendering (~16-33ms at 30-60 FPS)
- Frame time limits update visibility
- 60 FPS = 16.7ms between visible updates

**Total Expected Latency**: 80-180ms minimum

This explains the 100-300ms perceived delay noted in testing. It's a fundamental limitation of Bluetooth OBD.

## Optimization Techniques Implemented

### 1. Fast Query Timeout Tuning

```python
# obd_socket.py line 356
# Too fast (0.1s) caused connection failures
# Too slow (0.5s) reduces responsiveness
response = self._send_command(pid, timeout=0.3 if fast else 0.5)
```

**Rule of thumb**: Timeout should be 2-3x expected response time.

### 2. Prioritized PID Rotation (query_fast)

```python
def query_fast(self) -> OBDData:
    """Query single PIDs with throttle prioritized for responsiveness.

    Pattern: Throttle -> Throttle -> MAP -> Throttle -> Throttle -> RPM
    This gives throttle 4x more updates than boost/RPM.
    """
    pids = [
        ('0111', 'throttle_pos'),  # Throttle
        ('0111', 'throttle_pos'),  # Throttle again
        ('010B', 'map_kpa'),        # MAP for boost
        ('0111', 'throttle_pos'),  # Throttle
        ('0111', 'throttle_pos'),  # Throttle again
        ('010C', 'rpm'),            # RPM
    ]
```

Throttle gets 67% of queries because it changes fastest. MAP/RPM are slower-changing values.

### 3. Smoothing Factor Tuning

Current: `smoothing = 0.25`

- Lower (0.15): Very responsive but choppy
- Current (0.25): Balanced for RS7 + OBDLink MX+
- Higher (0.35+): Smooth but laggy

## Future Optimizations

### 1. Implement DecelerateInterpolator in pygame

```python
class AnimatedValue:
    def __init__(self, initial=0.0):
        self.current = initial
        self.target = initial
        self.start = initial
        self.start_time = 0
        self.duration = 0.1  # 100ms default

    def set_target(self, value):
        self.start = self.current
        self.target = value
        self.start_time = time.time()

    def update(self) -> float:
        elapsed = time.time() - self.start_time
        t = min(elapsed / self.duration, 1.0)
        # DecelerateInterpolator curve
        progress = 1 - (1 - t) ** 2
        self.current = self.start + (self.target - self.start) * progress
        return self.current
```

### 2. Adaptive Refresh Rate

Match animation duration to actual polling rate:
```python
# Track time between updates
last_update = time.time()

def on_data_received(value):
    global last_update
    now = time.time()
    actual_interval = now - last_update
    animation_duration = actual_interval  # Match to data rate
    last_update = now
```

### 3. Predictive Smoothing

For fast-changing values like throttle, predict where the value is going:
```python
# Simple velocity prediction
velocity = (current_value - previous_value) / time_delta
predicted = current_value + velocity * lookahead_time
```

## Test Results (2025-12-10)

After implementing fixes:
- Connection: Stable (no more timeout failures)
- Polling: ~5.2 Hz effective (26 callbacks in 5 seconds)
- User feedback: "looks much more responsive for throttle"
- Remaining delay: ~100-300ms (inherent Bluetooth limitation)

## References

### Source Files Analyzed

| File | Purpose |
|------|---------|
| `TorqueRefresher.kt` | Polling scheduler, staggered offsets |
| `TorqueGauge.kt` | Animation calls, update handler |
| `TorqueSpeedometer.kt` | Custom gauge (extends SpeedViewLib) |
| `SpeedViewLib/Gauge.kt` | Animation implementation |

### Useful Links

- [SpeedViewLib](https://github.com/anastr/SpeedView) - Android gauge library
- [aa-torque](https://github.com/agronick/aa-torque) - Android Auto OBD display
- [ELM327 commands](https://www.elmelectronics.com/wp-content/uploads/2016/07/ELM327DS.pdf) - AT command reference

---

**Last Updated:** 2025-12-10
**Based on:** aa-torque analysis session
