import { NavLink, Route, Routes } from "react-router-dom";
import { LayoutDashboard, Mail, KeyRound, PlusCircle } from "lucide-react";
import Dashboard from "./pages/Dashboard";
import Wizard from "./pages/Wizard";
import RunPage from "./pages/RunPage";
import SettingsSenders from "./pages/SettingsSenders";
import SettingsLLM from "./pages/SettingsLLM";

const link = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`;

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
          <div className="text-lg font-bold text-indigo-700">ApplyMail</div>
          <nav className="flex flex-wrap items-center gap-1">
            <NavLink to="/" end className={link}>
              <LayoutDashboard size={15} /> Dashboard
            </NavLink>
            <NavLink to="/runs/new" className={link}>
              <PlusCircle size={15} /> New run
            </NavLink>
            <NavLink to="/settings/senders" className={link}>
              <Mail size={15} /> Senders
            </NavLink>
            <NavLink to="/settings/llm" className={link}>
              <KeyRound size={15} /> LLM keys
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/new" element={<Wizard />} />
          <Route path="/runs/:id/edit" element={<Wizard />} />
          <Route path="/runs/:id" element={<RunPage />} />
          <Route path="/settings/senders" element={<SettingsSenders />} />
          <Route path="/settings/llm" element={<SettingsLLM />} />
          <Route path="*" element={<div className="card">Page not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}
