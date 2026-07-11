import { motion, AnimatePresence } from 'framer-motion'
import { Plus, FileText, CheckCircle, XCircle, Blocks, Settings } from 'lucide-react'
import DslEditor from '../components/DslEditor'
import { useStrategiesState } from '../hooks/useStrategiesState'
import StrategyListSection from '../components/strategies/StrategyListSection'
import InstanceFormModal from '../components/strategies/InstanceFormModal'
import TemplateManagementSection from '../components/strategies/TemplateManagementSection'

export default function StrategiesPage() {
  const state = useStrategiesState()

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 className="text-sm font-medium text-[#E8E8ED]">策略列表</h2>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => state.setShowNewTemplate(true)}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <FileText className="w-4 h-4" /> 自定义模板
          </button>
          <button
            onClick={() => state.setShowTemplateMgmt(true)}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <Settings className="w-4 h-4" /> 模板管理
          </button>
          <button
            onClick={state.handleOpenNewDslEditor}
            className="flex items-center gap-2 border border-[#1E1E28] text-[#E8E8ED] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[#1A1A24] transition-colors"
          >
            <Blocks className="w-4 h-4" /> QS-Model 策略构建
          </button>
          <button
            onClick={state.openCreateModal}
            className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-4 py-2 text-sm font-semibold hover:bg-[#00D4AA]/90 transition-colors"
          >
            <Plus className="w-4 h-4" /> 新建策略
          </button>
        </div>
      </div>

      <AnimatePresence>
        {state.toast && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className={`flex items-center gap-2 text-sm p-3 rounded-md border ${
              state.toast.type === 'success'
                ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                : 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20'
            }`}
          >
            {state.toast.type === 'success' ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {state.toast.msg}
          </motion.div>
        )}
      </AnimatePresence>

      <StrategyListSection
        instances={state.instances}
        loading={state.loading}
        expandedId={state.expandedId}
        setExpandedId={state.setExpandedId}
        actionLoading={state.actionLoading}
        savingParams={state.savingParams}
        instanceEvents={state.instanceEvents}
        feasibilityMsg={state.feasibilityMsg}
        setFeasibilityMsg={state.setFeasibilityMsg}
        getInstanceSchema={state.getInstanceSchema}
        handleStart={state.handleStart}
        handlePause={state.handlePause}
        handleResume={state.handleResume}
        handleStop={state.handleStop}
        handleDelete={state.handleDelete}
        handleParamSave={state.handleParamSave}
        setInstances={state.setInstances}
      />

      <InstanceFormModal
        open={state.showCreate}
        onClose={() => { state.setShowCreate(false); state.resetCreateForm() }}
        templates={state.templates}
        activeAccounts={state.activeAccounts}
        selectedTemplateId={state.selectedTemplateId}
        setSelectedTemplateId={state.setSelectedTemplateId}
        selectedAccountForCreate={state.selectedAccountForCreate}
        setSelectedAccountForCreate={state.setSelectedAccountForCreate}
        instanceName={state.instanceName}
        setInstanceName={state.setInstanceName}
        selectedMarketType={state.selectedMarketType}
        setSelectedMarketType={state.setSelectedMarketType}
        customParams={state.customParams}
        setCustomParams={state.setCustomParams}
        selectedTemplate={state.selectedTemplate}
        lockedBaseSymbol={state.lockedBaseSymbol}
        paramSchema={state.paramSchema}
        symbolSearch={state.symbolSearch}
        setSymbolSearch={state.setSymbolSearch}
        showSymbolDropdown={state.showSymbolDropdown}
        setShowSymbolDropdown={state.setShowSymbolDropdown}
        symbolDropdownRef={state.symbolDropdownRef}
        filteredSymbols={state.filteredSymbols}
        contractSymbols={state.contractSymbols}
        spotSymbols={state.spotSymbols}
        creating={state.creating}
        handleCreate={state.handleCreate}
      />

      <TemplateManagementSection
        showNewTemplate={state.showNewTemplate}
        setShowNewTemplate={state.setShowNewTemplate}
        showTemplateMgmt={state.showTemplateMgmt}
        setShowTemplateMgmt={state.setShowTemplateMgmt}
        templates={state.templates}
        onCreated={state.loadData}
        onEdit={state.handleEditTemplate}
        onDelete={state.handleDeleteTemplate}
        deletingTemplateId={state.deletingTemplateId}
      />

      <DslEditor
        open={state.showDslEditor}
        onClose={state.handleCloseDslEditor}
        onSaved={state.loadData}
        editingTemplateId={state.editingTemplateId}
        templates={state.templates}
      />
    </div>
  )
}
