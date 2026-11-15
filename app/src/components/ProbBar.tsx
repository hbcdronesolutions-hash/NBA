import { team } from "../teams";

/** Barre partagée : domicile à gauche, extérieur à droite. Repère fin = bookmakers. */
export function ProbBar({
  away,
  home,
  pHome,
  pBookHome,
  divergence,
  height = 6,
}: {
  away: string;
  home: string;
  pHome: number;
  pBookHome?: number | null;
  divergence?: boolean;
  height?: number;
}) {
  const awayW = (1 - pHome) * 100;
  const favHome = pHome >= 0.5;
  return (
    <div className="probbar" style={{ height }}>
      <div
        className="probbar-seg"
        style={{ width: `${100 - awayW}%`, background: favHome ? team(home).color : "var(--seg-muted)" }}
      />
      <div
        className="probbar-seg"
        style={{ width: `${awayW}%`, background: favHome ? "var(--seg-muted)" : team(away).color }}
      />
      {pBookHome != null && (
        <div
          className={`probbar-tick${divergence ? " is-alert" : ""}`}
          style={{ left: `${pBookHome * 100}%` }}
          title="Bookmakers"
        />
      )}
    </div>
  );
}
