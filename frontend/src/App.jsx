import { ThemeProvider } from "@mui/material/styles";
import theme from "./theme";
import CssBaseline from "@mui/material/CssBaseline";
import MainLayout from "./components/layout/MainLayout"; 
function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
     <MainLayout/>
    </ThemeProvider>
  );
}
export default App