import type { ApiHealth } from './api/types'
import { AppHeader } from './components/AppHeader'
import { ToolSection } from './components/ToolSection'
import { toolsForCategory } from './tools/catalog'

interface AppProps {
  checkHealth?: () => Promise<ApiHealth>
}

function App({ checkHealth }: AppProps) {
  return (
    <div className="app-shell">
      <AppHeader checkHealth={checkHealth} />
      <main id="main-content">
        <section className="intro" aria-labelledby="intro-heading">
          <p className="eyebrow">Document work, simplified</p>
          <h1 id="intro-heading">Choose the right tool for your file</h1>
          <p className="intro__copy">
            DocuForge brings focused PDF and image utilities into one clear
            workspace. The processing engine is ready; browser workflows arrive
            in the next frontend updates.
          </p>
        </section>

        <div className="catalog">
          <ToolSection
            title="PDF tools"
            description="Organize, refine, and transform PDF documents while keeping every operation focused."
            tools={toolsForCategory('pdf')}
          />
          <ToolSection
            title="Image tools"
            description="Prepare images for sharing, storage, and document workflows."
            tools={toolsForCategory('image')}
          />
        </div>
      </main>
      <footer className="app-footer">
        <p>DocuForge MVP · Local-first document processing foundations</p>
      </footer>
    </div>
  )
}

export default App
