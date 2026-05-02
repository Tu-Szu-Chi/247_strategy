from datetime import datetime
from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.data import DataManager, StreamKey
from qt_platform.indicators.runner import IndicatorRunner
from qt_platform.indicators.collection.force_score import ForceScoreIndicator
from qt_platform.indicators.collection.sma import SmaIndicator

# Define a custom derived indicator for testing DAG
class DerivedIndicator(Indicator):
    @property
    def name(self) -> str:
        return "derived_test"
    
    @property
    def dependencies(self) -> list[str]:
        return ["force_score", "sma_5"]
        
    def update(self, context) -> IndicatorValue:
        fs = context.get_dependency("force_score")
        sma = context.get_dependency("sma_5")
        val = (fs or 0) + (sma or 0)
        return IndicatorValue(value=val, timestamp=context.ts)

def test_runner():
    dm = DataManager()
    runner = IndicatorRunner(dm)
    
    # Mock some data
    stream_key = "shioaji:bars_1m:MTX"
    stream = dm.get_stream(stream_key)
    
    class MockBar:
        def __init__(self, close, volume, up_ticks, down_ticks):
            self.close = close
            self.volume = volume
            self.up_ticks = up_ticks
            self.down_ticks = down_ticks
            self.ts = datetime.now()

    # Seed with 5 bars
    for i in range(5):
        stream.append(MockBar(close=100 + i, volume=1000, up_ticks=10, down_ticks=5))
    
    # Setup pipeline
    configs = [
        {"indicator": ForceScoreIndicator(), "mapping": {"src": stream_key}},
        {"indicator": SmaIndicator(window=5), "mapping": {"src": stream_key}},
        {"indicator": DerivedIndicator(), "mapping": {}}
    ]
    
    runner.add_pipeline("test_1m", configs)
    pipeline = runner.get_pipeline("test_1m")
    
    print(f"Execution Order: {pipeline.execution_order}")
    
    # Run update
    now = datetime.now()
    runner.update_all(now)
    
    snapshot = pipeline.get_snapshot()
    print(f"Results: {snapshot}")
    
    # Verify DerivedIndicator
    fs_val = snapshot["force_score"]
    sma_val = snapshot["sma_5"]
    derived_val = snapshot["derived_test"]
    
    print(f"FS: {fs_val}, SMA: {sma_val}, Derived: {derived_val}")
    assert derived_val == fs_val + sma_val
    print("Test Passed!")

if __name__ == "__main__":
    test_runner()
