import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Workflows from './pages/Workflows';
import WorkflowDetail from './pages/WorkflowDetail';
import Intelligence from './pages/Intelligence';
import Investigations from './pages/Investigations';
import DataSources from './pages/DataSources';
import Artifacts from './pages/Artifacts';
import Governance from './pages/Governance';
import Observability from './pages/Observability';
import CompareRuns from './pages/CompareRuns';
import UsageCenter from './pages/UsageCenter';
import Settings from './pages/Settings';
import DataExplorer from './pages/DataExplorer';
import AIAnalyst from './pages/AIAnalyst';
import Visualizations from './pages/Visualizations';
import Monitoring from './pages/Monitoring';
import Operations from './pages/Operations';
import ScalableData from './pages/ScalableData';
export default function App(){return <Routes><Route element={<Layout/>}>
  <Route index element={<Home/>}/><Route path="workflows" element={<Workflows/>}/>
  <Route path="workflows/:runId" element={<WorkflowDetail/>}/>
  <Route path="intelligence" element={<Intelligence/>}/><Route path="analyst" element={<AIAnalyst/>}/><Route path="investigations" element={<Investigations/>}/>
  <Route path="data" element={<DataSources/>}/><Route path="data/explore" element={<DataExplorer/>}/>
  <Route path="artifacts" element={<Artifacts/>}/><Route path="visualizations" element={<Visualizations/>}/><Route path="compare" element={<CompareRuns/>}/>
  <Route path="scale" element={<ScalableData/>}/><Route path="monitoring" element={<Monitoring/>}/><Route path="operations" element={<Operations/>}/><Route path="usage" element={<UsageCenter/>}/><Route path="settings" element={<Settings/>}/>
  <Route path="governance" element={<Governance/>}/><Route path="observability" element={<Observability/>}/>
  <Route path="*" element={<Navigate to="/" replace/>}/>
</Route></Routes>}
