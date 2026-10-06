import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { I18nProvider } from "./i18n";
import { DemoPage } from "./pages/DemoPage";
import { EvalResults } from "./pages/EvalResults";
import { EvalScore } from "./pages/EvalScore";
import { Home } from "./pages/Home";

export function App() {
  return (
    <I18nProvider>
      <BrowserRouter>
        <div className="flex min-h-screen flex-col">
          <Header />
          <main className="flex-1">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/eval" element={<EvalScore />} />
              <Route path="/eval/results" element={<EvalResults />} />
              <Route path="/:demoId" element={<DemoPage />} />
            </Routes>
          </main>
          <Footer />
        </div>
      </BrowserRouter>
    </I18nProvider>
  );
}
