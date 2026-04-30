const fs = require('fs');
const path = 'frontend/src/features/option-power/components/TimelineCharts.tsx';
let content = fs.readFileSync(path, 'utf8');

const target = `    if (showsPricePanel) {
      const { candle, volume, ma10, ma30, ma60 } = priceSeriesRef.current;
      if (!candle || !volume || !ma10 || !ma30 || !ma60) {
        return;
      }
      candle.setData(normalizedBars);
      volume.setData(normalizedVolume);
      ma10.setData(normalizedData.ma10);
      ma30.setData(normalizedData.ma30);
      ma60.setData(normalizedData.ma60);
      dataRef.current.price = new Map(normalizedBars.map((item) => [Number(item.time), item]));
      representativeSeriesRef.current.price = candle;
    } else {
      dataRef.current.price = new Map();
      representativeSeriesRef.current.price = null;
    }

    for (const panel of visiblePanels) {
      if (panel.id === "price") {
        continue;
      }
      let representativeSet = false;
      const mergedData = new Map<number, LineData>();
      for (const series of panelData[panel.id]) {
        if (series.kind === "histogram") {
          const target = indicatorHistogramRef.current[series.id];
          if (!target) {
            continue;
          }
          const normalized = (normalizedData.panels[panel.id]?.[series.id] ?? []) as HistogramData[];
          target.setData(normalized);
          for (const item of normalized) {
            if (!mergedData.has(Number(item.time))) {
              mergedData.set(Number(item.time), {
                time: item.time,
                value: Number(item.value),
              });
            }
          }
          if (!representativeSet && normalized.length > 0) {
            representativeSeriesRef.current[panel.id] = target;
            representativeSet = true;
          }
          continue;
        }
        const target = indicatorSeriesRef.current[series.id];
        if (!target) {
          continue;
        }
        const normalized = (normalizedData.panels[panel.id]?.[series.id] ?? []) as LineData[];
        target.setData(normalized);
        for (const item of normalized) {
          if (!mergedData.has(Number(item.time))) {
            mergedData.set(Number(item.time), item);
          }
        }
        if (!representativeSet && normalized.length > 0) {
          representativeSeriesRef.current[panel.id] = target;
          representativeSet = true;
        }
      }
      dataRef.current[panel.id] = mergedData;
      if (!representativeSet) {
        representativeSeriesRef.current[panel.id] = null;
      }
    }`;

const replacement = `    // Helper for incremental update
    const syncSeriesData = (series: any, newData: any[], existingMap: Map<number, any>, updateMap?: Map<number, any>) => {
      if (newData.length === 0) {
        series.setData([]);
        if (updateMap) updateMap.clear();
        return;
      }
      if (existingMap.size === 0) {
        series.setData(newData);
        if (updateMap) {
          for (const item of newData) updateMap.set(Number(item.time), item);
        }
        return;
      }

      let maxTime = -Infinity;
      let minTime = Infinity;
      for (const t of existingMap.keys()) {
        if (t > maxTime) maxTime = t;
        if (t < minTime) minTime = t;
      }

      const firstNewTime = Number(newData[0].time);
      if (firstNewTime !== minTime || newData.length < existingMap.size - 2) {
        series.setData(newData);
        if (updateMap) {
          updateMap.clear();
          for (const item of newData) updateMap.set(Number(item.time), item);
        }
        return;
      }

      for (let i = 0; i < newData.length; i++) {
        const t = Number(newData[i].time);
        if (t >= maxTime) {
          series.update(newData[i]);
        }
        if (updateMap && t >= maxTime) {
          updateMap.set(t, newData[i]);
        }
      }
    };

    if (showsPricePanel) {
      const { candle, volume, ma10, ma30, ma60 } = priceSeriesRef.current;
      if (!candle || !volume || !ma10 || !ma30 || !ma60) {
        return;
      }
      const existingPriceMap = dataRef.current.price;
      
      syncSeriesData(candle, normalizedBars, existingPriceMap, existingPriceMap);
      
      // We don't need updateMap for these because we only use existingPriceMap to check the timeline
      syncSeriesData(volume, normalizedVolume, existingPriceMap);
      syncSeriesData(ma10, normalizedData.ma10, existingPriceMap);
      syncSeriesData(ma30, normalizedData.ma30, existingPriceMap);
      syncSeriesData(ma60, normalizedData.ma60, existingPriceMap);

      representativeSeriesRef.current.price = candle;
    } else {
      dataRef.current.price.clear();
      representativeSeriesRef.current.price = null;
    }

    for (const panel of visiblePanels) {
      if (panel.id === "price") {
        continue;
      }
      let representativeSet = false;
      const existingPanelMap = dataRef.current[panel.id] || new Map<number, any>();
      
      for (const series of panelData[panel.id]) {
        if (series.kind === "histogram") {
          const target = indicatorHistogramRef.current[series.id];
          if (!target) continue;
          
          const normalized = (normalizedData.panels[panel.id]?.[series.id] ?? []) as HistogramData[];
          syncSeriesData(target, normalized, existingPanelMap, existingPanelMap);
          
          if (!representativeSet && normalized.length > 0) {
            representativeSeriesRef.current[panel.id] = target;
            representativeSet = true;
          }
          continue;
        }
        
        const target = indicatorSeriesRef.current[series.id];
        if (!target) continue;
        
        const normalized = (normalizedData.panels[panel.id]?.[series.id] ?? []) as LineData[];
        syncSeriesData(target, normalized, existingPanelMap, existingPanelMap);
        
        if (!representativeSet && normalized.length > 0) {
          representativeSeriesRef.current[panel.id] = target;
          representativeSet = true;
        }
      }
      
      if (!representativeSet) {
        representativeSeriesRef.current[panel.id] = null;
      }
    }`;

if (content.includes(target)) {
  content = content.replace(target, replacement);
  fs.writeFileSync(path, content, 'utf8');
  console.log('Successfully updated TimelineCharts.tsx');
} else {
  console.log('Target not found in TimelineCharts.tsx');
}
