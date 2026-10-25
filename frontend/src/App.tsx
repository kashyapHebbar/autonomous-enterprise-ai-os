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
export default function App() {return <Routes><Route element={<Layout/>}><Route index element={<Home/>}/><Route path="workflows" element={<Workflows/>}/><Route path="workflows/:runId" element={<WorkflowDetail/>}/><Route path="intelligence" element={<Intelligence/>}/><Route path="investigations" element={<Investigations/>}/><Route path="data" element={<DataSources/>}/><Route path="artifacts" element={<Artifacts/>}/><Route path="governance" element={<Governance/>}/><Route path="observability" element={<Observability/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Route></Routes>}
