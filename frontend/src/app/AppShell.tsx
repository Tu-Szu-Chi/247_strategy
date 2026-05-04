import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import styles from "./AppShell.module.css";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Local Quant Workspace</p>
          <h1 className={styles.title}>qt-platform</h1>
        </div>
        <nav className={styles.nav}>
          <NavLink
            to="/research/live"
            className={({ isActive }) => (isActive ? styles.activeLink : styles.link)}
          >
            Research Live
          </NavLink>
          <NavLink
            to="/research/replay"
            className={({ isActive }) => (isActive ? styles.activeLink : styles.link)}
          >
            Research Replay
          </NavLink>
          <NavLink
            to="/portfolio"
            className={({ isActive }) => (isActive ? styles.activeLink : styles.link)}
          >
            Portfolio
          </NavLink>
        </nav>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
