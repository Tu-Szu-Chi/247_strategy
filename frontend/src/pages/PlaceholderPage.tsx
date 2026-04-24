import styles from "./PlaceholderPage.module.css";

type PlaceholderPageProps = {
  title: string;
  description: string;
};

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <section className={styles.card}>
      <p className={styles.label}>Planned Route</p>
      <h2 className={styles.title}>{title}</h2>
      <p className={styles.description}>{description}</p>
    </section>
  );
}
