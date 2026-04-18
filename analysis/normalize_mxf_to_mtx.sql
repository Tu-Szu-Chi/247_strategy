
UPDATE bars_1m
SET symbol = 'MTX'
WHERE symbol LIKE 'MXF*';

UPDATE bars_1d
SET symbol = 'MTX'
WHERE symbol LIKE 'MXF*';

UPDATE raw_ticks
SET symbol = 'MTX'
WHERE symbol LIKE 'MXF*';

UPDATE minute_force_features_1m
SET symbol = 'MTX'
WHERE symbol LIKE 'MXF*';

