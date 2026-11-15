import { team } from "../teams";

export function TeamLogo({ abbr, size = 40, dim = false }: { abbr: string; size?: number; dim?: boolean }) {
  const Logo = team(abbr).logo;
  return (
    <span className={`logo${dim ? " logo-dim" : ""}`} style={{ width: size, height: size }} aria-hidden>
      <Logo width={size} height={size} />
    </span>
  );
}
