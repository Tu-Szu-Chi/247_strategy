import styles from "./MetricCard.module.css";

type MetricCardProps = {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative";
};

export function MetricCard({ label, value, tone = "neutral" }: MetricCardProps) {
  return (
    <article className={styles.card} data-tone={tone}>
      <span className={styles.label}>{label}</span>
      <strong className={styles.value}>{value}</strong>
    </article>
  );
}
