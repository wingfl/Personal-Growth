import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/layout/Sidebar";
import { Topbar } from "./components/layout/Topbar";
import { Home } from "./pages/Home";
import { Archive } from "./pages/Archive";
import { Insights } from "./pages/Insights";
import { Capabilities } from "./pages/Capabilities";
import { Goals } from "./pages/Goals";
import { Review } from "./pages/Review";
import { Settings } from "./pages/Settings";

export default function App() {
  return (
    <div className="flex">
      <Sidebar />
      <div className="min-w-0 flex-1">
        <Topbar />
        <main className="mx-auto w-full max-w-[1280px] px-4 py-6 md:px-10 md:py-10">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/archive" element={<Archive />} />
            <Route path="/insights" element={<Insights />} />
            <Route path="/capabilities" element={<Capabilities />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/review" element={<Review />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Home />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
