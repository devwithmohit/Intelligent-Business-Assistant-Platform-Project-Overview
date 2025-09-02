import { ThemeProvider } from "@mui/material/styles";
import theme from "./theme";
import Dashboard from "./components/Dashboard/Dashboard";
import CssBaseline from "@mui/material/CssBaseline";
function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Dashboard />
    </ThemeProvider>
  );
}
export default App