import { ChartNoAxesColumn, CircleCheck, ListChecks, Moon, Target, UserRound } from "lucide-react";
import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/", label: "Ce soir", Icon: Moon },
  { to: "/joueurs", label: "Joueurs", Icon: UserRound },
  { to: "/resultats", label: "Résultats", Icon: ListChecks },
  { to: "/selection", label: "Sélection", Icon: Target },
  { to: "/forces", label: "Forces", Icon: ChartNoAxesColumn },
  { to: "/bilan", label: "Bilan", Icon: CircleCheck },
];

export function TabBar() {
  return (
    <nav className="tabbar">
      {TABS.map(({ to, label, Icon }) => (
        <NavLink key={to} to={to} end className={({ isActive }) => `tab${isActive ? " is-active" : ""}`}>
          <Icon size={22} strokeWidth={1.8} />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
