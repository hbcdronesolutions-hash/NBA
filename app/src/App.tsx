import { HashRouter, Route, Routes, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { TabBar } from "./components/TabBar";
import { Match } from "./screens/Match";
import { Ratings } from "./screens/Ratings";
import { Record } from "./screens/Record";
import { Results } from "./screens/Results";
import { Selection } from "./screens/Selection";
import { Tonight } from "./screens/Tonight";

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => window.scrollTo(0, 0), [pathname]);
  return null;
}

export default function App() {
  return (
    <HashRouter>
      <ScrollTop />
      <div className="app">
        <Routes>
          <Route path="/" element={<Tonight />} />
          <Route path="/match/:id" element={<Match />} />
          <Route path="/resultats" element={<Results />} />
          <Route path="/selection" element={<Selection />} />
          <Route path="/forces" element={<Ratings />} />
          <Route path="/bilan" element={<Record />} />
        </Routes>
        <TabBar />
      </div>
    </HashRouter>
  );
}
