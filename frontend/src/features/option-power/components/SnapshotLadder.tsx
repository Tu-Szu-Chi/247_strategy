import { buildStrikeRows, maxAbsPower, selectExpiry } from "../selectors";
import type { OptionPowerSnapshot } from "../types";
import styles from "./SnapshotLadder.module.css";

type SnapshotLadderProps = {
  snapshot: OptionPowerSnapshot | null;
  selectedExpiry: string;
  onExpiryChange: (value: string) => void;
};

export function SnapshotLadder({
  snapshot,
  selectedExpiry,
  onExpiryChange,
}: SnapshotLadderProps) {
  const expiry = selectExpiry(snapshot, selectedExpiry);
  const rows = buildStrikeRows(expiry);
  const scaleBase = maxAbsPower(expiry);

  return (
    <section className={styles.card}>
      <div className={styles.toolbar}>
        <div>
          <p className={styles.label}>Expiry</p>
          <select
            className={styles.select}
            value={expiry?.contract_month ?? ""}
            onChange={(event) => onExpiryChange(event.target.value)}
          >
            {(snapshot?.expiries ?? []).map((item) => (
              <option key={item.contract_month} value={item.contract_month}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.legend}>
          <span>Call</span>
          <span>Put</span>
        </div>
      </div>

      <div className={styles.header}>
        <div>Strike</div>
        <div>Call</div>
        <div>Put</div>
      </div>

      {rows.length === 0 ? (
        <div className={styles.empty}>該時間點沒有 option snapshot。</div>
      ) : (
        <div className={styles.rows}>
          {rows.map((row) => (
            <div key={row.strike} className={styles.row}>
              <div className={styles.strike}>{row.strike}</div>
              <PowerCell contract={row.call} scaleBase={scaleBase} />
              <PowerCell contract={row.put} scaleBase={scaleBase} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

type PowerCellProps = {
  contract?: {
    cumulative_power: number;
    power_1m_delta: number;
    last_price: number | null;
  };
  scaleBase: number;
};

function PowerCell({ contract, scaleBase }: PowerCellProps) {
  if (!contract) {
    return <div className={styles.cellMuted}>-</div>;
  }
  const magnitude = Math.abs(contract.cumulative_power);
  const normalized = Math.min(1, magnitude / Math.max(scaleBase, 1));
  const emphasized = Math.pow(normalized, 0.72);
  const width = `${Math.min(100, Math.max(magnitude > 0 ? 8 : 0, Math.round(emphasized * 100)))}%`;
  const tone = contract.cumulative_power > 0 ? "positive" : contract.cumulative_power < 0 ? "negative" : "neutral";
  return (
    <div className={styles.cell}>
      <div className={styles.cellTop}>
        <span>{formatPrice(contract.last_price)}</span>
        <strong className={styles.delta} data-tone={tone}>
          {formatSigned(contract.power_1m_delta)}
        </strong>
      </div>
      <div className={styles.barTrack}>
        <div
          className={styles.barFill}
          data-tone={tone}
          data-strong={normalized >= 0.85 ? "true" : "false"}
          style={{ width }}
        />
      </div>
      <div className={styles.cellBottom}>
        <strong>{formatSigned(contract.cumulative_power)}</strong>
        <span className={styles.powerLabel}>power</span>
      </div>
    </div>
  );
}

function formatSigned(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(0)}`;
}

function formatPrice(value: number | null) {
  if (value === null) {
    return "-";
  }
  return value >= 100 ? value.toFixed(0) : value.toFixed(1);
}
