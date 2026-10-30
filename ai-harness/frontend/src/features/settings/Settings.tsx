// Настройки — оболочка вкладок (DOM design_mockup/settings.js): set-tabs (role=tablist)
// + set-body с роутингом по #settings/<tab>. Содержимое вкладок живёт в tabs/*:
// FlowTab (Status-flow), ProvidersTab, ProjectsTab, AgentsTab, ToolsTab,
// QueueTab, JournalTab; общие константы — в shared.ts.

import { TABS, useSettingsTab } from './shared'
import { ToolsTab } from './ToolsTab'
import { FlowEditor } from './tabs/FlowTab'
import { Projects } from './tabs/ProjectsTab'
import { Providers } from './tabs/ProvidersTab'
import { AgentsAndMatrix } from './tabs/AgentsTab'
import { Queue } from './tabs/QueueTab'
import { Journal } from './tabs/JournalTab'

export function Settings({ reload }: { reload: () => void }) {
  const tab = useSettingsTab()
  return (
    <div className="settings">
      <div className="set-tabs" role="tablist">
        {TABS.map(([v, l]) => (
          <button key={v} className={`set-tab ${tab === v ? 'active' : ''}`}
            onClick={() => { window.location.hash = `#settings/${v}` }}>{l}</button>
        ))}
      </div>
      <div className="set-body">
        {tab === 'flow' && <FlowEditor reload={reload} />}
        {tab === 'projects' && <Projects />}
        {tab === 'providers' && <Providers />}
        {tab === 'agents' && <AgentsAndMatrix />}
        {tab === 'tools' && <ToolsTab />}
        {tab === 'queue' && <Queue />}
        {tab === 'journal' && <Journal />}
      </div>
    </div>
  )
}
