const MODES = [
  {
    id: "leaf_first",
    label: "知识点优先",
    description: "先补知识点，再做题。",
  },
  {
    id: "question_first",
    label: "题目优先",
    description: "先做题，再补知识点。",
  },
  {
    id: "mixed",
    label: "混合自动",
    description: "让系统自动安排。",
  },
];

const state = {
  mode: "leaf_first",
  dashboard: null,
  student: {
    student_id: "",
    storage_mode: "",
    storage_label: "",
    database_enabled: false,
  },
  studentDirectory: [],
  activeTab: "import",
  importDraft: null,
  tree: null,
  wrongbook: null,
  selectedTreeNodeId: null,
  selectedWrongbookNodeId: null,
  treeLookup: {},
  treeRoots: [],
  treeParentLookup: {},
  wrongbookLookup: {},
  wrongbookRoots: [],
  wrongbookParentLookup: {},
  wrongbookExpandedNodeIds: new Set(),
  diagnosisFlow: {
    active: false,
    phase: "idle",
    chat_history: [],
    pending_diagnosis: null,
    can_continue: false,
    can_enter_coach: false,
    coach_ready: false,
  },
  coachChat: {
    active: false,
    chat_history: [],
    done: false,
    stop_reason: null,
    turn_index: 0,
    max_turns: 0,
  },
  loading: {
    diagnosis: false,
    coach: false,
  },
};

function emptyDiagnosisFlow() {
  return {
    active: false,
    phase: "idle",
    chat_history: [],
    pending_diagnosis: null,
    can_continue: false,
    can_enter_coach: false,
    coach_ready: false,
  };
}

function emptyCoachChat() {
  return {
    active: false,
    chat_history: [],
    done: false,
    stop_reason: null,
    turn_index: 0,
    max_turns: 0,
  };
}

const TABS = [
  { id: "import", label: "拍题", cue: "OCR", icon: "📸" },
  { id: "diagnosis", label: "诊断", cue: "看问题", icon: "🩺" },
  { id: "coach", label: "引导", cue: "继续学", icon: "💬" },
  { id: "wrongbook", label: "错题本", cue: "按点整理", icon: "🗂" },
  { id: "review", label: "再练", cue: "系统推题", icon: "🎯" },
];

const WORKFLOW_STEPS = [
  { id: "import", label: "拍题", desc: "先出草稿", icon: "📸", order: "01" },
  { id: "diagnosis", label: "诊断", desc: "判断错因", icon: "🩺", order: "02" },
  { id: "coach", label: "引导", desc: "继续讲解", icon: "💬", order: "03" },
  { id: "wrongbook", label: "存题", desc: "挂到知识点", icon: "🗂", order: "04" },
  { id: "review", label: "再练", desc: "安排复习", icon: "🎯", order: "05" },
];

const TARGET_LABELS = {
  diagnosis: "诊断",
  coach: "引导",
  wrongbook: "错题本",
};
const IMPORT_FIELD_LABELS = {
  question: "题目",
  answer: "答案",
  solution: "解析",
};

const MEMORY_STAGE_LABELS = {
  early_observation: "早期观察",
  forming_pattern: "形成规律",
  stable_pattern: "稳定规律",
  unknown: "未知",
};

const ERROR_TYPE_LABELS = {
  concept_gap: "概念漏洞",
  missing_strategy: "缺少思路",
  misreading: "读题偏差",
  calculation: "计算错误",
  careless: "粗心失误",
  unknown: "未知",
};

const WRONGBOOK_SOURCE_TYPE_LABELS = {
  ocr_direct: "OCR 直入",
  diagnosis_transfer: "诊断转入",
  coach_transfer: "引导转入",
  manual_entry: "手动加入",
  binder_import: "系统绑定导入",
};

const REVIEW_MODE_LABELS = {
  leaf_first: "知识点优先",
  question_first: "题目优先",
  mixed: "混合自动",
};

const TEACHING_MODE_LABELS = {
  concept_first: "先讲概念",
  strategy_first: "先讲思路",
  step_by_step: "分步引导",
  condition_first: "先审条件",
  self_check_first: "先自检纠错",
  balanced: "均衡模式",
  socratic_standard: "标准苏格拉底引导",
  socratic_light: "轻苏格拉底引导",
  direct_explanation: "直接讲解",
  guided_breakdown: "拆解式引导",
};

const COACH_REPLY_QUALITY_LABELS = {
  empty: "几乎没答出来",
  weak: "方向有了但不完整",
  good: "回答较完整",
};

const COACH_STOP_REASON_LABELS = {
  continue: "继续追问",
  student_understood: "学生已基本理解",
  max_turns: "达到本轮上限",
  unknown: "未标注",
};

const DIAGNOSIS_STANCE_LABELS = {
  confirm: "基本认可",
  reject: "明确反驳",
  unclear: "仍不清楚",
};

const DIAGNOSIS_STOP_REASON_LABELS = {
  continue_confirmation: "继续确认",
  await_confirmation: "等待学生确认",
  enter_coach_after_confirmation: "确认后进入引导",
  enter_coach_after_max_confirm: "达到确认上限后进入引导",
  continue: "继续",
  unknown: "未标注",
};

const NODE_KIND_LABELS = {
  concept: "概念",
  formula: "公式",
  method: "方法",
  application: "应用",
  custom: "自定义",
  unknown: "未标注",
};

const CARD_TYPE_LABELS = {
  concept_card: "概念卡",
  formula_card: "公式卡",
  method_card: "方法卡",
  example_card: "例题卡",
  error_card: "易错卡",
  representative_question: "代表题",
  card: "卡片",
  unknown: "未标注",
};

function localizedMemoryStage(value) {
  const key = String(value || "").trim();
  return MEMORY_STAGE_LABELS[key] || key || "无";
}

function localizedErrorType(value) {
  const key = String(value || "").trim();
  return ERROR_TYPE_LABELS[key] || key || "无";
}

function localizedWrongbookSourceType(value) {
  const key = String(value || "").trim();
  return WRONGBOOK_SOURCE_TYPE_LABELS[key] || key || "未标注来源";
}

function localizedReviewMode(value) {
  const key = String(value || "").trim();
  return REVIEW_MODE_LABELS[key] || key || "无";
}

function localizedTeachingMode(value) {
  const key = String(value || "").trim();
  return TEACHING_MODE_LABELS[key] || key || "无";
}

function localizedReplyQuality(value) {
  const key = String(value || "").trim();
  return COACH_REPLY_QUALITY_LABELS[key] || key || "无";
}

function localizedCoachStopReason(value) {
  const key = String(value || "").trim();
  return COACH_STOP_REASON_LABELS[key] || key || "未标注";
}

function localizedDiagnosisStance(value) {
  const key = String(value || "").trim();
  return DIAGNOSIS_STANCE_LABELS[key] || key || "未标注";
}

function localizedDiagnosisStopReason(value) {
  const key = String(value || "").trim();
  return DIAGNOSIS_STOP_REASON_LABELS[key] || key || "未标注";
}

function localizedNodeKind(value) {
  const key = String(value || "").trim();
  return NODE_KIND_LABELS[key] || key || "未标注";
}

function localizedCardType(value) {
  const key = String(value || "").trim();
  return CARD_TYPE_LABELS[key] || key || "未标注";
}

function localizedQuestionResult(value) {
  const key = String(value || "").trim();
  if (!key || key === "unseen") return "未做";
  if (key === "correct") return "做对";
  if (key === "wrong") return "做错";
  if (key === "partial") return "部分正确";
  if (key === "skip") return "已跳过";
  return key;
}

function buildImportDraft(ocr = {}) {
  return {
    filename: ocr.filename || "",
    source_name: ocr.prefill?.source_name || (ocr.filename ? `MinerU OCR · ${ocr.filename}` : "MinerU OCR"),
    question_text: ocr.question_text || "",
    answer_text: ocr.answer_text || "",
    solution_text: ocr.solution_text || "",
    preview_text: ocr.preview_text || "",
    warnings: Array.isArray(ocr.warnings) ? ocr.warnings : [],
  };
}

function ensureImportEditorVisible() {
  const panel = $("importResultPanel");
  if (!panel) return;
  if ($("importQuestionText") && $("importAnswerText") && $("importSolutionText")) {
    return;
  }
  renderImportResult($("importTarget")?.value || "wrongbook", state.importDraft || {});
}

function readImportDraftFromEditor() {
  const base = state.importDraft || {};
  return {
    ...base,
    source_name: $("importSourceName")?.value?.trim() || base.source_name || "",
    question_text: $("importQuestionText")?.value || base.question_text || "",
    answer_text: $("importAnswerText")?.value || base.answer_text || "",
    solution_text: $("importSolutionText")?.value || base.solution_text || "",
  };
}

async function polishImportAnswerAndSolution() {
  const draft = readImportDraftFromEditor();
  const button = $("importPolishBtn");
  if (!draft.question_text.trim() && !draft.answer_text.trim() && !draft.solution_text.trim()) {
    showStatus("先填入题目、答案或解析，再整理思路");
    return;
  }
  setButtonBusy(button, true, "整理中...");
  try {
    const payload = await fetchJson("/api/import/polish-answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question_text: draft.question_text,
        answer_text: draft.answer_text,
        solution_text: draft.solution_text,
      }),
    });
    const polish = payload.polish || {};
    renderImportPolishResult(polish);
    if (polish.polished_answer && $("importAnswerText")) {
      $("importAnswerText").value = polish.polished_answer;
      state.importDraft = readImportDraftFromEditor();
    }
    showStatus("已整理答案并提炼思路");
  } finally {
    setButtonBusy(button, false);
  }
}

function renderImportPolishResult(polish) {
  const panel = $("importPolishResult");
  if (!panel) return;
  panel.innerHTML = "";
  if (!polish) return;
  const card = create("div", "ocr-feedback-card");
  card.append(
    create("p", "ocr-feedback-title", "答案整理结果"),
    create("p", "ocr-feedback-text", `缓存：${polish.cached ? "是" : "否"}`)
  );
  if (polish.polished_answer) {
    card.append(
      create("p", "ocr-feedback-title", "整理后的答案"),
      create("p", "ocr-feedback-text", polish.polished_answer)
    );
  }
  if (polish.thinking_summary) {
    card.append(
      create("p", "ocr-feedback-title", "解题思路"),
      create("p", "ocr-feedback-text", polish.thinking_summary)
    );
  }
  panel.appendChild(card);
}

function applyImportDraftToDiagnosis(draft) {
  const questionText = String(draft.question_text || "").trim();
  const answerText = String(draft.answer_text || "").trim();
  const solutionText = String(draft.solution_text || "").trim();
  $("diagnosisProblemText").value = questionText;
  $("diagnosisReferenceAnswer").value = [answerText, solutionText].filter(Boolean).join("\n\n");
  if ($("diagnosisStudentAnswer")) $("diagnosisStudentAnswer").value = "";
  if ($("diagnosisFollowupInput")) $("diagnosisFollowupInput").value = "";
  state.diagnosisFlow = emptyDiagnosisFlow();
  renderDiagnosisOutput();
}

function applyImportDraftToWrongbook(draft) {
  if (!$("wrongbookPrimaryNodeId").value.trim() && state.selectedWrongbookNodeId) {
    $("wrongbookPrimaryNodeId").value = state.selectedWrongbookNodeId;
  }
  $("wrongbookStem").value = String(draft.question_text || "").trim();
  $("wrongbookCorrectAnswer").value = String(draft.answer_text || "").trim();
  $("wrongbookSolutionText").value = String(draft.solution_text || "").trim();
  $("wrongbookSourceName").value = String(draft.source_name || "").trim();
  $("wrongbookSourceType").value = "ocr_direct";
}

function latestStudentCoachReply() {
  const history = state.coachChat?.chat_history || [];
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const message = history[index];
    if (message?.role === "student" && String(message.content || "").trim()) {
      return String(message.content || "").trim();
    }
  }
  return "";
}

function moveCoachToWrongbook() {
  const problemText = String(state.coachChat?.problem_text || $("coachProblemText")?.value || "").trim();
  const studentAnswer = latestStudentCoachReply() || String($("coachStudentReply")?.value || "").trim();
  if (!problemText) {
    showStatus("当前没有可转入错题本的题目");
    return;
  }
  if (!$("wrongbookPrimaryNodeId").value.trim() && state.selectedWrongbookNodeId) {
    $("wrongbookPrimaryNodeId").value = state.selectedWrongbookNodeId;
  }
  $("wrongbookStem").value = problemText;
  if (studentAnswer) {
    $("wrongbookStudentAnswer").value = studentAnswer;
  }
  if (!$("wrongbookSourceName").value.trim()) {
    $("wrongbookSourceName").value = "Coach 引导转入";
  }
  $("wrongbookSourceType").value = "coach_transfer";
  const coachErrorType = String(state.coachChat?.error_type || $("coachErrorType")?.value || "").trim();
  if (coachErrorType && !$("wrongbookPriorityNote").value.trim()) {
    $("wrongbookPriorityNote").value = `来自引导环节，当前主要错因：${localizedErrorType(coachErrorType)}。`;
  }
  state.activeTab = "wrongbook";
  syncPanels();
  showStatus("已把当前引导题目填入错题本");
}

function latestDiagnosisPayload() {
  const history = state.diagnosisFlow?.chat_history || [];
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const message = history[index];
    if (message?.role === "assistant" && message?.diagnosis) {
      return message.diagnosis;
    }
  }
  return null;
}

function moveDiagnosisToWrongbook() {
  const diagnosis = latestDiagnosisPayload();
  const problemText = String(
    state.diagnosisFlow?.pending_diagnosis?.problem_text
      || diagnosis?.problem_text
      || $("diagnosisProblemText")?.value
      || ""
  ).trim();
  const studentAnswer = String(
    diagnosis?.student_answer
      || state.diagnosisFlow?.chat_history?.find?.((item) => item?.kind === "initial_answer")?.content
      || $("diagnosisStudentAnswer")?.value
      || ""
  ).trim();
  const referenceAnswer = String(
    diagnosis?.reference_answer || $("diagnosisReferenceAnswer")?.value || ""
  ).trim();
  if (!problemText) {
    showStatus("当前没有可转入错题本的诊断题目");
    return;
  }
  if (!$("wrongbookPrimaryNodeId").value.trim() && state.selectedWrongbookNodeId) {
    $("wrongbookPrimaryNodeId").value = state.selectedWrongbookNodeId;
  }
  $("wrongbookStem").value = problemText;
  if (studentAnswer) {
    $("wrongbookStudentAnswer").value = studentAnswer;
  }
  if (referenceAnswer && !$("wrongbookCorrectAnswer").value.trim()) {
    $("wrongbookCorrectAnswer").value = referenceAnswer;
  }
  if (!$("wrongbookSourceName").value.trim()) {
    $("wrongbookSourceName").value = "Diagnosis 诊断转入";
  }
  $("wrongbookSourceType").value = "diagnosis_transfer";
  const diagnosisErrorType = String(diagnosis?.error_type || "").trim();
  if (diagnosisErrorType && !$("wrongbookPriorityNote").value.trim()) {
    const reason = String(diagnosis?.reason || "").trim();
    $("wrongbookPriorityNote").value = reason
      ? `来自诊断环节，当前主要错因：${localizedErrorType(diagnosisErrorType)}。${reason}`
      : `来自诊断环节，当前主要错因：${localizedErrorType(diagnosisErrorType)}。`;
  }
  if (!$("wrongbookQuestionNote").value.trim()) {
    const evidence = String(diagnosis?.evidence || "").trim();
    if (evidence) {
      $("wrongbookQuestionNote").value = `诊断证据：${evidence}`;
    }
  }
  state.activeTab = "wrongbook";
  syncPanels();
  showStatus("已把当前诊断题目填入错题本");
}

const PAGE_INTROS = {
  review: {
    icon: "🎯",
    title: "再练",
    body: "系统把该练的题放在这里。",
  },
  import: {
    icon: "📸",
    title: "拍题",
    body: "先把题目变成草稿。",
  },
  diagnosis: {
    icon: "🩺",
    title: "看问题",
    body: "先看学生错在哪。",
  },
  coach: {
    icon: "💬",
    title: "继续学",
    body: "按当前卡点继续讲。",
  },
  wrongbook: {
    icon: "🗂",
    title: "错题本",
    body: "按知识点存题。",
  },
};

function $(id) {
  return document.getElementById(id);
}

function create(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

async function fetchFormJson(url, formData) {
  const response = await fetch(url, {
    method: "POST",
    body: formData,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "上传失败");
  }
  return payload;
}

function syncStudentStateFromDashboard(payload = state.dashboard) {
  const student = payload?.student || {};
  const session = payload?.session || {};
  const reviewSummary = payload?.review_state_summary || {};
  state.student = {
    student_id: String(
      student.student_id
      || session.student_id
      || reviewSummary.student_id
      || state.student.student_id
      || ""
    ).trim(),
    storage_mode: String(
      student.storage_mode
      || session.storage_mode
      || state.student.storage_mode
      || ""
    ).trim(),
    storage_label: String(
      student.storage_label
      || session.storage_label
      || state.student.storage_label
      || ""
    ).trim(),
    database_enabled: Boolean(
      student.database_enabled !== undefined
        ? student.database_enabled
        : state.student.database_enabled
    ),
  };
}

function setButtonBusy(button, active, busyLabel = "处理中...") {
  if (!button) return;
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent || "";
  }
  button.disabled = active;
  button.classList.toggle("waiting", active);
  button.textContent = active ? busyLabel : button.dataset.defaultLabel;
}

function updateFileNameLabel(labelId, file) {
  const label = $(labelId);
  if (!label) return;
  if (!file) {
    label.textContent = "未选择文件";
    return;
  }
  if (Array.isArray(file)) {
    if (!file.length) {
      label.textContent = "未选择文件";
      return;
    }
    const totalMb = file.reduce((sum, item) => sum + (item.size || 0), 0) / 1024 / 1024;
    const previewNames = file.slice(0, 3).map((item) => item.name).join("，");
    const suffix = file.length > 3 ? ` 等 ${file.length} 个文件` : ` · 共 ${file.length} 个文件`;
    label.textContent = `${previewNames}${suffix} · ${totalMb.toFixed(2)} MB`;
    return;
  }
  label.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
}

function rerenderMath() {
  if (window.MathJax && window.MathJax.typesetPromise) {
    window.MathJax.typesetPromise().catch((error) => console.error(error));
  }
}

async function loadDashboard() {
  const payload = await fetchJson(`/api/dashboard?mode=${encodeURIComponent(state.mode)}`);
  state.dashboard = payload;
  state.mode = payload.session?.mode || state.mode;
  syncStudentStateFromDashboard(payload);
  render();
}

async function loadStudentDirectory() {
  const payload = await fetchJson("/api/students");
  state.studentDirectory = Array.isArray(payload.students) ? payload.students : [];
}

async function applyAction(actionPayload) {
  const payload = await fetchJson("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...actionPayload,
      mode: state.mode,
    }),
  });
  state.dashboard = payload.dashboard;
  render();
  showStatus("已更新本轮复习状态");
}

async function resetSession() {
  const payload = await fetchJson("/api/reset");
  state.dashboard = payload;
  state.mode = payload.session.mode;
  syncStudentStateFromDashboard(payload);
  state.activeTab = "import";
  state.diagnosisFlow = emptyDiagnosisFlow();
  state.coachChat = emptyCoachChat();
  await loadStudentDirectory();
  render();
  showStatus("复习会话已重置");
}

function applyWorkspacePayload(payload) {
  if (payload.student) {
    state.student = {
      ...state.student,
      ...payload.student,
    };
  }
  if (Array.isArray(payload.students)) {
    state.studentDirectory = payload.students;
  }
  if (payload.dashboard) {
    state.dashboard = payload.dashboard;
    state.mode = payload.dashboard.session?.mode || state.mode;
    syncStudentStateFromDashboard(payload.dashboard);
  }
  if (payload.tree) {
    applyTreePayload(payload.tree);
  }
  if (payload.wrongbook) {
    applyWrongbookPayload(payload.wrongbook);
  }
  if (payload.flow) {
    state.diagnosisFlow = payload.flow;
  } else if (payload.flow === null) {
    state.diagnosisFlow = emptyDiagnosisFlow();
  }
  if (payload.chat) {
    state.coachChat = payload.chat;
  } else if (payload.chat === null) {
    state.coachChat = emptyCoachChat();
  }
}

function resetStudentScopedViewState() {
  state.tree = null;
  state.wrongbook = null;
  state.selectedTreeNodeId = null;
  state.selectedWrongbookNodeId = null;
  state.treeLookup = {};
  state.treeRoots = [];
  state.treeParentLookup = {};
  state.wrongbookLookup = {};
  state.wrongbookRoots = [];
  state.wrongbookParentLookup = {};
  state.wrongbookExpandedNodeIds = new Set();
  state.diagnosisFlow = emptyDiagnosisFlow();
  state.coachChat = emptyCoachChat();
}

async function switchStudent(nextStudentId = null) {
  const input = $("studentIdInput");
  const studentId = String(nextStudentId ?? input?.value ?? "").trim();
  if (!studentId) {
    showStatus("先填学生 ID");
    return;
  }
  const button = $("switchStudentBtn");
  setButtonBusy(button, true, "切换中...");
  try {
    const payload = await fetchJson("/api/student/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: studentId,
      }),
    });
    resetStudentScopedViewState();
    applyWorkspacePayload(payload);
    await Promise.all([loadTree(), loadWrongbook(), loadDiagnosisState(), loadCoachState(), loadStudentDirectory()]);
    state.activeTab = "import";
    render();
    showStatus(
      `已切换到学生 ${state.student.student_id} · 错题本 ${state.wrongbook?.question_count ?? 0} 道`
    );
  } catch (error) {
    console.error(error);
    showStatus(`切换失败：${error.message}`);
  } finally {
    setButtonBusy(button, false);
  }
}

async function loadTree() {
  const payload = await fetchJson("/api/tree");
  applyTreePayload(payload);
  renderTree();
}

async function loadWrongbook() {
  const payload = await fetchJson("/api/wrongbook");
  applyWrongbookPayload(payload);
  renderWrongbook();
}

async function loadDiagnosisState() {
  const payload = await fetchJson("/api/diagnosis/state");
  state.diagnosisFlow = payload.flow || emptyDiagnosisFlow();
}

async function loadCoachState() {
  const payload = await fetchJson("/api/coach/state");
  state.coachChat = payload.chat || emptyCoachChat();
}

const OCR_TARGET_CONFIG = {
  diagnosis: {
    applyPrefill(prefill) {
      if (prefill.problem_text) $("diagnosisProblemText").value = prefill.problem_text;
      if (prefill.reference_answer) $("diagnosisReferenceAnswer").value = prefill.reference_answer;
    },
    async autoAction() {
      if (!$("diagnosisStudentAnswer").value.trim()) {
        showStatus("OCR 已填入题目和答案，但学生回答为空，暂未自动开始诊断");
        return;
      }
      await runDiagnosis();
    },
  },
  coach: {
    applyPrefill(prefill) {
      if (prefill.problem_text) $("coachProblemText").value = prefill.problem_text;
      if (prefill.student_reply) $("coachStudentReply").value = prefill.student_reply;
    },
    async autoAction() {
      if (!$("coachStudentReply").value.trim()) {
        showStatus("OCR 已填入题目，但学生当前回复为空，暂未自动开始引导");
        return;
      }
      await runCoach();
    },
  },
  wrongbook: {
    applyPrefill(prefill) {
      if (!$("wrongbookPrimaryNodeId").value.trim() && state.selectedWrongbookNodeId) {
        $("wrongbookPrimaryNodeId").value = state.selectedWrongbookNodeId;
      }
      if (prefill.stem) $("wrongbookStem").value = prefill.stem;
      if (prefill.correct_answer) $("wrongbookCorrectAnswer").value = prefill.correct_answer;
      if (prefill.solution_text) $("wrongbookSolutionText").value = prefill.solution_text;
      if (prefill.source_name) $("wrongbookSourceName").value = prefill.source_name;
    },
    async autoAction() {
      if (!$("wrongbookPrimaryNodeId").value.trim()) {
        showStatus("OCR 已填入错题内容，但主知识点为空，未自动加入错题本");
        return;
      }
      if (!$("wrongbookStem").value.trim()) {
        showStatus("OCR 没有稳定识别出题干，未自动加入错题本");
        return;
      }
      await createWrongbookQuestion();
    },
  },
};

function renderOcrFeedback(target, ocr) {
  const container = $("importOcrFeedback");
  if (!container) return;
  container.innerHTML = "";
  if (!ocr) return;

  const card = create("div", "ocr-feedback-card");
  card.append(
    create("p", "ocr-feedback-title", `已识别：${ocr.filename || "文件"}`),
    create(
      "p",
      "ocr-feedback-text",
      `文件数：${ocr.file_count || 1} · 预览长度：${(ocr.preview_text || "").length} 字\n运行目录：${ocr.run_dir || "-"}`
    )
  );
  container.appendChild(card);

  if (Array.isArray(ocr.files) && ocr.files.length > 1) {
    const filesCard = create("div", "ocr-feedback-card");
    filesCard.append(
      create("p", "ocr-feedback-title", "本次合并文件"),
      create("p", "ocr-feedback-text", ocr.files.map((item, index) => `${index + 1}. ${item.filename}`).join("\n"))
    );
    container.appendChild(filesCard);
  }

  if (Array.isArray(ocr.files) && ocr.files.length) {
    const roleCard = create("div", "ocr-feedback-card");
    roleCard.append(
      create("p", "ocr-feedback-title", "单文件识别")
    );
    ocr.files.forEach((item, index) => {
      const confidence =
        Number.isFinite(Number(item.detected_role_confidence))
          ? ` · 置信度 ${(Number(item.detected_role_confidence) * 100).toFixed(0)}%`
          : "";
      const lines = [
        `${index + 1}. ${item.filename || "文件"}`,
        `识别结果：${item.detected_role_label || item.detected_role || "未判断"}${confidence}`,
      ];
      if (Array.isArray(item.detected_role_reasons) && item.detected_role_reasons.length) {
        lines.push(`理由：${item.detected_role_reasons.join("；")}`);
      }
      const lengths = [
        `题干 ${String(item.question_text || "").length} 字`,
        `答案 ${String(item.answer_text || "").length} 字`,
        `解析 ${String(item.solution_text || "").length} 字`,
      ];
      lines.push(`拆分结果：${lengths.join(" · ")}`);
      roleCard.appendChild(create("p", "ocr-feedback-text", lines.join("\n")));
    });
    container.appendChild(roleCard);
  }

  if (ocr.warnings?.length) {
    const warningCard = create("div", "ocr-feedback-card");
    warningCard.append(
      create("p", "ocr-feedback-title", "识别提醒"),
      create("p", "ocr-feedback-text", ocr.warnings.join("\n"))
    );
    container.appendChild(warningCard);
  }

  if (ocr.preview_excerpt) {
    const previewCard = create("div", "ocr-feedback-card");
    previewCard.append(
      create("p", "ocr-feedback-title", "OCR 预览"),
      create("p", "ocr-feedback-text", ocr.preview_excerpt)
    );
    container.appendChild(previewCard);
  }
}

function populateImportFieldModes(target) {
  const select = $("importFieldMode");
  if (!select) return;
  const optionsByTarget = {
    diagnosis: [
      ["auto", "自动拆分题目 + 参考答案"],
      ["problem", "整段填入题目"],
      ["reference", "整段填入标准答案"],
    ],
    coach: [
      ["auto", "自动填入题目"],
      ["student_reply", "整段填入学生回复"],
    ],
    wrongbook: [
      ["auto", "自动拆分题干 + 答案 + 解析"],
      ["stem", "整段填入题目"],
      ["answer_solution", "整段填入答案 / 解析"],
    ],
  };
  const options = optionsByTarget[target] || optionsByTarget.wrongbook;
  select.innerHTML = "";
  options.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  });
}

function renderImportResult(target, ocr) {
  const panel = $("importResultPanel");
  if (!panel) return;
  panel.innerHTML = "";
  if (!ocr && !state.importDraft) return;
  state.importDraft = buildImportDraft(ocr);
  const draft = state.importDraft;

  const intro = create("div", "ocr-feedback-card");
  intro.append(
    create("p", "ocr-feedback-title", `目标页面：${TARGET_LABELS[target] || target}`),
    create("p", "ocr-feedback-text", `题干 ${String(draft.question_text || "").length} 字 · 答案 ${String(draft.answer_text || "").length} 字 · 解析 ${String(draft.solution_text || "").length} 字`)
  );
  panel.appendChild(intro);

  const editor = create("div", "ocr-feedback-card");
  const sourceField = create("label", "field");
  sourceField.append(
    create("span", null, "来源名称"),
    Object.assign(document.createElement("input"), {
      id: "importSourceName",
      type: "text",
      value: draft.source_name || "",
    })
  );
  const questionField = create("label", "field");
  questionField.append(
    create("span", null, "题干"),
    Object.assign(document.createElement("textarea"), {
      id: "importQuestionText",
      rows: 8,
      value: draft.question_text || "",
    })
  );
  const answerField = create("label", "field");
  answerField.append(
    create("span", null, "答案"),
    Object.assign(document.createElement("textarea"), {
      id: "importAnswerText",
      rows: 4,
      value: draft.answer_text || "",
    })
  );
  const solutionField = create("label", "field");
  solutionField.append(
    create("span", null, "解析"),
    Object.assign(document.createElement("textarea"), {
      id: "importSolutionText",
      rows: 6,
      value: draft.solution_text || "",
    })
  );
  editor.append(
    create("p", "ocr-feedback-title", "可编辑 OCR 草稿"),
    create("p", "ocr-feedback-text", "改好再继续。"),
    sourceField,
    questionField,
    answerField,
    solutionField
  );
  panel.appendChild(editor);

  const actionCard = create("div", "ocr-feedback-card");
  actionCard.append(
    create("p", "ocr-feedback-title", "下一步"),
    create("p", "ocr-feedback-text", "整理后再送到下一页。")
  );
  const actions = create("div", "chat-inline-actions");
  const polishBtn = create("button", "ghost-btn", "整理答案与思路");
  polishBtn.type = "button";
  polishBtn.id = "importPolishBtn";
  polishBtn.addEventListener("click", polishImportAnswerAndSolution);
  const wrongbookBtn = create("button", "ghost-btn primary-btn", "前往错题本");
  wrongbookBtn.type = "button";
  wrongbookBtn.addEventListener("click", () => {
    const currentDraft = readImportDraftFromEditor();
    state.importDraft = currentDraft;
    applyImportDraftToWrongbook(currentDraft);
    state.activeTab = "wrongbook";
    syncPanels();
    showStatus("已把当前 OCR 草稿填入错题本");
  });
  const diagnosisBtn = create("button", "ghost-btn", "前往诊断");
  diagnosisBtn.type = "button";
  diagnosisBtn.addEventListener("click", () => {
    const currentDraft = readImportDraftFromEditor();
    state.importDraft = currentDraft;
    applyImportDraftToDiagnosis(currentDraft);
    state.activeTab = "diagnosis";
    syncPanels();
    showStatus("已把当前 OCR 草稿填入诊断");
  });
  actions.append(polishBtn, wrongbookBtn, diagnosisBtn);
  actionCard.appendChild(actions);
  actionCard.appendChild(create("div", "import-polish-result"));
  actionCard.lastChild.id = "importPolishResult";
  panel.appendChild(actionCard);
}

function extractSingleFieldText(fieldKey, ocr) {
  const prefill = ocr?.prefill || {};
  const fallback = String(ocr?.preview_text || "").trim();
  if (fieldKey === "question") {
    return String(prefill.stem || ocr?.question_text || fallback || "").trim();
  }
  if (fieldKey === "answer") {
    return String(prefill.correct_answer || ocr?.answer_text || fallback || "").trim();
  }
  if (fieldKey === "solution") {
    return String(prefill.solution_text || ocr?.solution_text || fallback || "").trim();
  }
  return fallback;
}

function applyFieldOcrResult(fieldKey, ocr) {
  ensureImportEditorVisible();
  const currentDraft = readImportDraftFromEditor();
  const nextDraft = {
    ...currentDraft,
    filename: currentDraft.filename || ocr.filename || "",
    source_name: currentDraft.source_name || ocr.prefill?.source_name || (ocr.filename ? `MinerU OCR · ${ocr.filename}` : "MinerU OCR"),
  };
  const text = extractSingleFieldText(fieldKey, ocr);

  if (fieldKey === "question") {
    nextDraft.question_text = text;
  } else if (fieldKey === "answer") {
    nextDraft.answer_text = text;
  } else if (fieldKey === "solution") {
    nextDraft.solution_text = text;
  }

  state.importDraft = nextDraft;
  if ($("importSourceName")) $("importSourceName").value = nextDraft.source_name || "";
  if ($("importQuestionText")) $("importQuestionText").value = nextDraft.question_text || "";
  if ($("importAnswerText")) $("importAnswerText").value = nextDraft.answer_text || "";
  if ($("importSolutionText")) $("importSolutionText").value = nextDraft.solution_text || "";
}

async function runOcrImport() {
  const target = $("importTarget")?.value || "wrongbook";
  const fileInput = $("importOcrFile");
  const button = $("importOcrBtn");
  const mode = $("importFieldMode")?.value || "auto";
  const files = Array.from(fileInput?.files || []);
  if (!files.length) {
    showStatus("先选择至少一张图片或一个 PDF");
    return;
  }

  const formData = new FormData();
  formData.append("target", target);
  formData.append("field_mode", mode);
  files.forEach((file) => {
    formData.append("file", file, file.name);
  });

  setButtonBusy(button, true, "MinerU 识别中...");
  try {
    const payload = await fetchFormJson("/api/ocr/extract", formData);
    const ocr = payload.ocr || {};
    renderOcrFeedback(target, ocr);
    renderImportResult(target, ocr);
    showStatus("MinerU 识别完成，请先检查并修改 OCR 草稿");
  } finally {
    setButtonBusy(button, false);
  }
}

async function runFieldOcrImport(fieldKey) {
  const inputIdByField = {
    question: "importQuestionOcrFile",
    answer: "importAnswerOcrFile",
    solution: "importSolutionOcrFile",
  };
  const buttonIdByField = {
    question: "importQuestionOcrBtn",
    answer: "importAnswerOcrBtn",
    solution: "importSolutionOcrBtn",
  };
  const modeByField = {
    question: "stem",
    answer: "answer_solution",
    solution: "answer_solution",
  };
  const input = $(inputIdByField[fieldKey]);
  const button = $(buttonIdByField[fieldKey]);
  const files = Array.from(input?.files || []);
  if (!files.length) {
    showStatus(`先选择${IMPORT_FIELD_LABELS[fieldKey] || "对应字段"}文件`);
    return;
  }

  const formData = new FormData();
  formData.append("target", "wrongbook");
  formData.append("field_mode", modeByField[fieldKey] || "auto");
  files.forEach((file) => {
    formData.append("file", file, file.name);
  });

  setButtonBusy(button, true, "识别中...");
  try {
    const payload = await fetchFormJson("/api/ocr/extract", formData);
    const ocr = payload.ocr || {};
    renderOcrFeedback("wrongbook", ocr);
    applyFieldOcrResult(fieldKey, ocr);
    showStatus(`${IMPORT_FIELD_LABELS[fieldKey] || "字段"} OCR 已写入编辑区`);
  } finally {
    setButtonBusy(button, false);
  }
}

function setupOcrDropzone(dropzoneId, fileInputId, fileNameId) {
  const dropzone = $(dropzoneId);
  const input = $(fileInputId);
  if (!dropzone || !input) return;

  input.addEventListener("change", () => {
    updateFileNameLabel(fileNameId, Array.from(input.files || []));
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", (event) => {
    const files = event.dataTransfer?.files;
    if (!files || !files.length) return;
    input.files = files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function runDiagnosis() {
  state.diagnosisFlow = emptyDiagnosisFlow();
  state.coachChat = emptyCoachChat();
  renderDiagnosisOutput();
  renderCoachOutput();
  setLoading("diagnosis", true, $("runDiagnosisBtn"));
  try {
    const payload = await fetchJson("/api/diagnosis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem_text: $("diagnosisProblemText").value,
        reference_answer: $("diagnosisReferenceAnswer").value,
        student_answer: $("diagnosisStudentAnswer").value,
        student_profile: $("diagnosisStudentProfile").value,
        max_turns: Number($("diagnosisCoachMaxTurns").value || 8),
      }),
    });
    state.diagnosisFlow = payload.flow || state.diagnosisFlow;
    renderDiagnosisOutput();
    showStatus("诊断结果已返回");
  } finally {
    setLoading("diagnosis", false, $("runDiagnosisBtn"));
  }
}

async function runCoach() {
  setLoading("coach", true, $("runCoachBtn"));
  try {
    const payload = await fetchJson("/api/coach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem_text: $("coachProblemText").value,
        error_type: $("coachErrorType").value,
        student_reply: $("coachStudentReply").value,
        student_profile: $("coachStudentProfile").value,
        max_turns: Number($("coachMaxTurns").value || 8),
      }),
    });
    state.coachChat = payload.chat || state.coachChat;
    renderCoachOutput();
    showStatus("引导结果已返回");
  } finally {
    setLoading("coach", false, $("runCoachBtn"));
  }
}

async function continueDiagnosis() {
  setLoading("diagnosis", true, $("continueDiagnosisBtn"));
  try {
    const payload = await fetchJson("/api/diagnosis/continue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_reply: $("diagnosisFollowupInput").value,
      }),
    });
    $("diagnosisFollowupInput").value = "";
    state.diagnosisFlow = payload.flow || state.diagnosisFlow;
    renderDiagnosisOutput();
    showStatus("诊断确认已继续");
  } finally {
    setLoading("diagnosis", false, $("continueDiagnosisBtn"));
  }
}

async function cancelDiagnosis() {
  const payload = await fetchJson("/api/diagnosis/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  state.diagnosisFlow = payload.flow || state.diagnosisFlow;
  renderDiagnosisOutput();
  showStatus("诊断会话已停止");
}

async function diagnosisToCoach() {
  setLoading("diagnosis", true, $("diagnosisToCoachBtn"));
  try {
    const payload = await fetchJson("/api/diagnosis/to-coach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    state.diagnosisFlow = payload.flow || state.diagnosisFlow;
    state.coachChat = payload.chat || state.coachChat;
    state.activeTab = "coach";
    syncPanels();
    renderDiagnosisOutput();
    renderCoachOutput();
    showStatus("已进入引导");
  } finally {
    setLoading("diagnosis", false, $("diagnosisToCoachBtn"));
  }
}

async function continueCoach() {
  setLoading("coach", true, $("continueCoachBtn"));
  try {
    const payload = await fetchJson("/api/coach/continue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_reply: $("coachFollowupInput").value,
      }),
    });
    $("coachFollowupInput").value = "";
    state.coachChat = payload.chat || state.coachChat;
    renderCoachOutput();
    showStatus("引导已继续");
  } finally {
    setLoading("coach", false, $("continueCoachBtn"));
  }
}

async function resumeCoach() {
  setLoading("coach", true, $("resumeCoachBtn"));
  try {
    const payload = await fetchJson("/api/coach/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    state.coachChat = payload.chat || state.coachChat;
    renderCoachOutput();
    showStatus("已恢复当前引导会话，可以继续提问");
  } finally {
    setLoading("coach", false, $("resumeCoachBtn"));
  }
}

async function cancelCoach() {
  const payload = await fetchJson("/api/coach/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  state.coachChat = payload.chat || state.coachChat;
  renderCoachOutput();
  showStatus("引导会话已停止");
}

async function createTreeNode() {
  const parentField = $("treeParentNodeId");
  const titleField = $("treeNodeTitle");
  if (!parentField || !titleField) {
    showStatus("当前界面没有开放 tree 编辑入口");
    return;
  }
  const parentNodeId = parentField.value;
  const title = titleField.value;
  const payload = await fetchJson("/api/tree/node", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      parent_node_id: parentNodeId,
      title,
      description: $("treeNodeDescription").value,
    }),
  });
  applyTreePayload(payload);
  if (parentNodeId && title) {
    state.selectedTreeNodeId = `${parentNodeId}.${title.replaceAll(" ", "_").replaceAll("/", "_")}`;
  }
  renderTree();
  showStatus("新节点已加入本地树");
}

async function createWrongbookNode() {
  const payload = await fetchJson("/api/wrongbook/node", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      parent_node_id: $("wrongbookParentNodeId").value,
      title: $("wrongbookNodeTitle").value,
      description: $("wrongbookNodeDescription").value,
    }),
  });
  if (payload.tree) {
    applyTreePayload(payload.tree);
  }
  if (payload.wrongbook) {
    applyWrongbookPayload(payload.wrongbook);
  }
  const parentNodeId = $("wrongbookParentNodeId").value;
  const title = $("wrongbookNodeTitle").value;
  if (parentNodeId && title) {
    state.selectedWrongbookNodeId = `${parentNodeId}.${title.replaceAll(" ", "_").replaceAll("/", "_")}`;
    $("wrongbookPrimaryNodeId").value = state.selectedWrongbookNodeId;
  }
  await loadStudentDirectory();
  renderTree();
  renderWrongbook();
  renderStudentDirectory();
  showStatus("错题本知识点已新建");
}

async function createWrongbookQuestion() {
  const payload = await fetchJson("/api/wrongbook/question", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      primary_node_id: $("wrongbookPrimaryNodeId").value,
      secondary_node_ids: $("wrongbookSecondaryNodeIds").value,
      question_id: $("wrongbookQuestionId").value,
      question_type: $("wrongbookQuestionType").value,
      stem: $("wrongbookStem").value,
      student_answer: $("wrongbookStudentAnswer").value,
      correct_answer: $("wrongbookCorrectAnswer").value,
      solution_text: $("wrongbookSolutionText").value,
      source_name: $("wrongbookSourceName").value,
      source_type: $("wrongbookSourceType").value,
      source_chapter: $("wrongbookSourceChapter").value,
      priority_note: $("wrongbookPriorityNote").value,
      note: $("wrongbookQuestionNote").value,
    }),
  });
  applyWorkspacePayload(payload);
  if (payload.created_question_id) {
    $("wrongbookQuestionId").value = payload.created_question_id;
  }
  state.selectedWrongbookNodeId = $("wrongbookPrimaryNodeId").value || state.selectedWrongbookNodeId;
  await Promise.all([loadDashboard(), loadTree(), loadWrongbook(), loadStudentDirectory()]);
  render();
  showStatus(`错题已加入错题本：${payload.created_question_id || "已保存"}`);
}

async function saveTreeNote(questionId, note) {
  const payload = await fetchJson("/api/tree/note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question_id: questionId,
      note,
    }),
  });
  applyTreePayload(payload);
  renderTree();
  showStatus("笔记已保存");
}

async function saveWrongbookNote(questionId, note) {
  const payload = await fetchJson("/api/wrongbook/note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question_id: questionId,
      note,
    }),
  });
  if (payload.tree) {
    applyTreePayload(payload.tree);
  }
  if (payload.wrongbook) {
    applyWrongbookPayload(payload.wrongbook);
  }
  renderTree();
  renderWrongbook();
  showStatus("错题本笔记已保存");
}

function applyTreePayload(payload) {
  state.tree = payload;
  const index = buildTreeIndex(payload.tree || []);
  state.treeLookup = index.lookup;
  state.treeRoots = index.roots;
  state.treeParentLookup = index.parentLookup;
  if (!state.selectedTreeNodeId || !state.treeLookup[state.selectedTreeNodeId]) {
    state.selectedTreeNodeId = state.treeRoots[0]?.node_id || null;
  }
}

function applyWrongbookPayload(payload) {
  state.wrongbook = payload;
  const index = buildTreeIndex(payload.tree || []);
  state.wrongbookLookup = index.lookup;
  state.wrongbookRoots = index.roots;
  state.wrongbookParentLookup = index.parentLookup;
  if (!state.selectedWrongbookNodeId || !state.wrongbookLookup[state.selectedWrongbookNodeId]) {
    state.selectedWrongbookNodeId = state.wrongbookRoots[0]?.node_id || null;
  }
  if (!state.wrongbookExpandedNodeIds.size && state.wrongbookRoots.length) {
    state.wrongbookRoots.forEach((node) => {
      state.wrongbookExpandedNodeIds.add(node.node_id);
    });
  }
  ensureWrongbookExpandedPath(state.selectedWrongbookNodeId);
}

function renderTabbar() {
  const container = $("tabbar");
  container.innerHTML = "";
  TABS.forEach((tab) => {
    const button = create("button", `tab-btn${state.activeTab === tab.id ? " active" : ""}`);
    button.type = "button";
    button.append(
      create("span", "tab-btn-icon", tab.icon),
      create("strong", "tab-btn-title", tab.label),
      create("span", "tab-btn-cue", tab.cue)
    );
    button.addEventListener("click", () => {
      state.activeTab = tab.id;
      syncPanels();
    });
    container.appendChild(button);
  });
}

function renderWorkflowStrip() {
  const container = $("workflowStrip");
  if (!container) return;
  container.innerHTML = "";
  WORKFLOW_STEPS.forEach((step) => {
    const button = create("button", `workflow-step${state.activeTab === step.id ? " active" : ""}`);
    button.type = "button";
    const top = create("div", "workflow-step-top");
    top.append(
      create("span", "workflow-step-icon", step.icon),
      create("span", "workflow-step-order", step.order)
    );
    const copy = create("div", "workflow-step-copy");
    copy.append(
      create("strong", null, step.label),
      create("span", null, step.desc)
    );
    button.append(top, copy);
    button.addEventListener("click", () => {
      state.activeTab = step.id;
      syncPanels();
    });
    container.appendChild(button);
  });
}

function renderQuickStartCard() {
  const container = $("quickStartCard");
  if (!container) return;
  container.innerHTML = "";
  const strip = create("div", "quick-start-strip");
  TABS.forEach((tab) => {
    const item = create("button", "quick-start-item");
    item.type = "button";
    item.append(
      create("span", "quick-start-icon", tab.icon),
      create("span", "quick-start-label", tab.label)
    );
    item.addEventListener("click", () => {
      state.activeTab = tab.id;
      syncPanels();
    });
    strip.appendChild(item);
  });
  container.append(
    create("p", "section-tag", "怎么用"),
    create("h3", "card-title", "像工具箱一样点进去"),
    create("p", "memory-note", "先拍题，再诊断、引导、存题，最后再练。"),
    strip
  );
}

function syncPanels() {
  document.querySelectorAll(".panel").forEach((node) => {
    node.classList.toggle("active", node.dataset.panel === state.activeTab);
  });
  renderPageIntro();
  renderWorkflowStrip();
  renderTabbar();
  if (state.activeTab === "wrongbook" && state.wrongbook) {
    renderWrongbook();
  }
  rerenderMath();
}

function renderPageIntro() {
  const container = $("pageIntro");
  if (!container) return;
  const content = PAGE_INTROS[state.activeTab] || PAGE_INTROS.import;
  container.innerHTML = "";
  const icon = create("div", "page-intro-icon", content.icon || "•");
  const copy = create("div", "page-intro-copy");
  copy.append(
    create("h2", null, content.title),
    create("p", null, content.body)
  );
  container.append(
    icon,
    copy
  );
}

function renderModeSwitch() {
  const container = $("modeSwitch");
  container.innerHTML = "";
  MODES.forEach((mode) => {
    const button = create("button", `mode-btn${state.mode === mode.id ? " active" : ""}`);
    button.type = "button";
    const title = create("strong", null, mode.label);
    const desc = create("span", null, mode.description);
    button.append(title, desc);
    button.addEventListener("click", async () => {
      state.mode = mode.id;
      await loadDashboard();
    });
    container.appendChild(button);
  });
}

function renderStudentCard() {
  const input = $("studentIdInput");
  const meta = $("studentStorageMeta");
  const currentSummary = state.studentDirectory.find(
    (item) => item?.student_id === state.student.student_id
  );
  if (input && document.activeElement !== input) {
    input.value = state.student.student_id || "";
  }
  if (meta) {
    const currentStudentId = state.student.student_id || "未命名";
    const storageLabel = state.student.storage_label || "未知存储";
    const wrongbookCount = currentSummary?.wrongbook_question_count ?? state.wrongbook?.question_count ?? 0;
    const reviewCount = currentSummary?.question_count ?? state.dashboard?.review_state_summary?.question_count ?? 0;
    meta.innerHTML = "";
    const strip = create("span", "student-meta-strip");
    [
      { icon: "👤", text: currentStudentId },
      { icon: "💾", text: storageLabel },
      { icon: "🗂", text: `${wrongbookCount} 道错题` },
      { icon: "🎯", text: `${reviewCount} 道复习` },
    ].forEach((item) => {
      const pill = create("span", "student-meta-pill");
      pill.append(
        create("span", "student-meta-icon", item.icon),
        create("span", "student-meta-text", item.text)
      );
      strip.appendChild(pill);
    });
    meta.appendChild(strip);
  }
}

function renderStudentDirectory() {
  const container = $("studentDirectory");
  if (!container) return;
  container.innerHTML = "";
  if (!state.studentDirectory.length) {
    container.appendChild(create("p", "memory-note", "还没有学生目录。"));
    return;
  }

  state.studentDirectory.forEach((item) => {
    const studentId = String(item?.student_id || "").trim();
    if (!studentId) return;
    const button = create(
      "button",
      `student-directory-item${studentId === state.student.student_id ? " active" : ""}`
    );
    button.type = "button";
    button.addEventListener("click", () => {
      $("studentIdInput").value = studentId;
      switchStudent(studentId);
    });

    const copy = create("span", "student-directory-copy");
    copy.append(
      create("strong", "student-directory-name", studentId),
      create(
        "span",
        "student-directory-meta",
        `错题 ${item.wrongbook_question_count ?? 0} · 复习 ${item.question_count ?? 0}`
      )
    );
    button.append(
      create("span", "student-directory-avatar", "学"),
      copy
    );
    container.appendChild(button);
  });
}

function renderSessionSummary() {
  const session = state.dashboard.session;
  const reviewSummary = state.dashboard.review_state_summary;
  const container = $("sessionSummary");
  container.innerHTML = "";

  const tag = create("p", "section-tag", "再练");
  const title = create("h2", "card-title", "系统推题");
  const grid = create("div", "summary-grid");

  [
    ["复习模式", modeLabel(session.mode)],
    ["待复习单元", String(session.bundle_count)],
    ["知识点", String(reviewSummary.knowledge_point_count)],
    ["复习题数", String(reviewSummary.question_count)],
  ].forEach(([label, value]) => {
    const item = create("div", "summary-item");
    item.append(create("span", null, label), create("strong", null, value));
    grid.appendChild(item);
  });

  const meta = create(
    "p",
    "memory-note",
    `学生：${state.student.student_id || reviewSummary.student_id || "未命名"} · 存储：${state.student.storage_label || session.storage_label || "-"} · 生成时间：${session.generated_at || "-"}`
  );

  container.append(tag, title, grid, meta);
}

function renderMemoryCard() {
  const memory = state.dashboard.memory_summary;
  const container = $("memoryCard");
  container.innerHTML = "";

  container.append(
    create("p", "section-tag", "长期画像"),
    create("h3", "card-title", "系统当前对学生的判断")
  );

  const grid = create("div", "summary-grid");
  [
    ["阶段", localizedMemoryStage(memory.memory_stage)],
    ["主错因", localizedErrorType(memory.dominant_error_type)],
    ["推荐复习模式", localizedReviewMode(memory.recommended_review_mode)],
    ["推荐教学模式", localizedTeachingMode(memory.recommended_teaching_mode)],
  ].forEach(([label, value]) => {
    const item = create("div", "summary-item");
    item.append(create("span", null, label), create("strong", null, value));
    grid.appendChild(item);
  });
  container.appendChild(grid);

  if (memory.notes && memory.notes.length) {
    memory.notes.slice(0, 2).forEach((note) => {
      container.appendChild(create("p", "memory-note", note));
    });
  }

  if (memory.top_recurrent_nodes && memory.top_recurrent_nodes.length) {
    const stack = create("div", "linked-card-stack");
    memory.top_recurrent_nodes.slice(0, 3).forEach((node) => {
      const card = create("div", "mini-card");
      card.append(
        create("p", "section-tag", "常卡知识点"),
        create("h4", "card-title", node.title || node.node_id),
        create(
          "p",
          "meta-text",
          `错因：${localizedErrorType(node.dominant_error_type)} · 观察阶段：${localizedMemoryStage(node.observation_stage)}`
        )
      );
      stack.appendChild(card);
    });
    container.appendChild(stack);
  }
}

function renderBundles() {
  const bundleList = $("bundleList");
  const bundles = state.dashboard.bundles.review_bundles || [];
  const reviewPlan = state.dashboard.bundles.review_plan || {};
  $("bundleMeta").textContent = `当前模式：${modeLabel(reviewPlan.mode)} · 推荐 ${bundles.length} 个复习单元`;
  bundleList.innerHTML = "";

  if (!bundles.length) {
    const empty = create("div", "bundle-card");
    empty.append(
      create("p", "section-tag", "空状态"),
      create("h3", "card-title", "当前没有可展示的复习单元"),
      create("p", "bundle-reason", "说明目前状态已被跳过、后移，或样例数据已经跑空。")
    );
    bundleList.appendChild(empty);
    return;
  }

  bundles.forEach((bundle) => {
    bundleList.appendChild(renderBundle(bundle));
  });
}

function renderBundle(bundle) {
  const card = create("article", "bundle-card");
  const top = create("div", "bundle-top");
  const left = create("div");
  left.append(
    create("p", "bundle-rank", `${bundle.bundle_id} / ${modeLabel(bundle.mode)}`),
    create(
      "h3",
      "bundle-title",
      bundle.mode === "leaf_first"
        ? bundle.leaf_card?.title || bundle.node_id
        : bundle.question?.summary?.question_type
          ? `${bundle.question.summary.question_type} · ${bundle.question_id}`
          : bundle.question_id
    ),
    create("p", "bundle-reason", bundle.bundle_reason || " ")
  );
  const score = create("div", "score-pill", `score ${formatScore(bundle.priority_score)}`);
  score.textContent = `分数 ${formatScore(bundle.priority_score)}`;
  top.append(left, score);
  card.appendChild(top);

  const grid = create(
    "div",
    `bundle-grid ${bundle.mode === "leaf_first" ? "leaf-first" : "question-first"}`
  );

  if (bundle.mode === "leaf_first") {
    grid.append(renderLeafCard(bundle.leaf_card), renderQuestionStack(bundle.questions || []));
  } else {
    grid.append(
      renderSingleQuestion(bundle.question),
      renderLinkedCards(bundle.linked_leaf_cards || [])
    );
  }

  card.appendChild(grid);
  return card;
}

function renderLeafCard(leafCard) {
  const card = create("section", "leaf-card");
  if (!leafCard) {
    card.append(
      create("p", "section-tag", "知识点"),
      create("h4", "card-title", "没有找到对应卡片")
    );
    return card;
  }

  card.append(
    create("p", "section-tag", "叶子卡片"),
    create("h4", "card-title", leafCard.title || leafCard.node_id),
    create("p", "card-subtitle", `${localizedCardType(leafCard.card_type)} · ${localizedNodeKind(leafCard.node_kind)}`)
  );

  if (leafCard.path && leafCard.path.length) {
    card.appendChild(create("p", "path-text", `路径：${leafCard.path.join(" > ")}`));
  }
  if (leafCard.keywords && leafCard.keywords.length) {
    const row = create("div", "pill-row");
    leafCard.keywords.slice(0, 8).forEach((keyword) => {
      row.appendChild(create("span", "pill", keyword));
    });
    card.appendChild(row);
  }
  card.appendChild(renderLeafStructuredBlocks(leafCard));

  const actions = normalizePrimaryActions(leafCard.student_actions || []);
  card.appendChild(renderActionRow(actions));
  return card;
}

function renderLeafStructuredBlocks(leafCard) {
  const wrap = create("div", "content-blocks");
  const structured = leafCard.structured_content || {};
  const blocks = [
    ["核心内容", leafCard.text],
    ["定义", structured.definition],
    ["核心思路", structured.core_idea],
    ["公式", structured.formula],
    ["变量说明", structured.variable_notes],
    ["适用条件", joinValue(structured.applicable_conditions)],
    ["特殊情况", joinValue(structured.special_cases)],
    ["目标", structured.method_goal],
    ["触发信号", joinValue(structured.trigger_signals)],
    ["步骤", joinValue(structured.steps)],
    ["常见错误", joinValue(structured.common_errors || structured.failure_modes)],
    ["复习提示", leafCard.review_cue],
  ];
  blocks.forEach(([label, value]) => {
    if (!value) return;
    const block = create("div", "content-block");
    block.append(
      create("h5", null, label),
      create("p", "content-value", value)
    );
    wrap.appendChild(block);
  });
  return wrap;
}

function renderQuestionStack(questions) {
  const wrap = create("div", "question-stack");
  if (!questions.length) {
    const empty = create("section", "question-card");
    empty.append(
      create("p", "section-tag", "配套题"),
      create("h4", "card-title", "这轮没有附带题目")
    );
    wrap.appendChild(empty);
    return wrap;
  }

  questions.forEach((question) => {
    wrap.appendChild(renderSingleQuestion(question));
  });
  return wrap;
}

function renderSingleQuestion(question) {
  const card = create("section", "question-card");
  const summary = question.summary || {};
  const content = question.content || {};
  const hidden = question.hidden_answer_block || {};

  card.append(
    create("p", "section-tag", "题目"),
    create("h4", "card-title", question.question_id || "未命名题目"),
    create(
      "p",
      "question-meta",
      `${summary.question_type || "题型未标注"} · 上次结果：${localizedQuestionResult(summary.last_result)} · 当前分数：${formatScore(summary.priority_score)}`
    )
  );

  if (content.stem) {
    card.appendChild(create("div", "question-content", content.stem));
  }
  if (content.student_answer) {
    card.appendChild(create("p", "meta-text", `学生答案：${content.student_answer}`));
  }

  const toggle = create("button", "toggle-answer", "显示答案与解析");
  toggle.type = "button";
  const answerBlock = create("div", "answer-block");
  answerBlock.append(
    create("span", "answer-label", "标准答案"),
    create("div", "question-content", hidden.correct_answer || "暂无"),
    create("span", "answer-label", "参考解析"),
    create("div", "question-content", hidden.solution_text || "暂无")
  );
  toggle.addEventListener("click", () => {
    answerBlock.classList.toggle("visible");
  });

  card.append(toggle, answerBlock, renderActionRow(question.student_actions || []));
  return card;
}

function renderDiagnosisOutput() {
  const container = $("diagnosisOutput");
  container.innerHTML = "";
  const flow = state.diagnosisFlow;
  syncLivePanels();
  renderWaitingOverlay(container, state.loading.diagnosis, "正在诊断与整理确认问题");

  if (!flow.chat_history?.length) {
    const empty = create("div", "bundle-card output-card");
    empty.append(
      create("p", "section-tag", "诊断"),
      create("h3", "card-title", "先填题目、答案、学生回答"),
      create("p", "bundle-reason", "开始后，这里会显示判断结果。")
    );
    container.appendChild(empty);
    rerenderMath();
    return;
  }

  const thread = create("div", "chat-thread");
  flow.chat_history.forEach((message) => {
    thread.appendChild(renderDiagnosisMessage(message));
  });
  container.appendChild(thread);
  rerenderMath();
}

function renderCoachOutput() {
  const container = $("coachOutput");
  container.innerHTML = "";
  const chat = state.coachChat;
  syncLivePanels();
  renderWaitingOverlay(container, state.loading.coach, "正在生成下一轮 coach 回复");

  if (!chat.chat_history?.length) {
    const empty = create("div", "bundle-card output-card");
    empty.append(
      create("p", "section-tag", "引导"),
      create("h3", "card-title", "先开始，或从诊断进入"),
      create("p", "bundle-reason", "开始后，这里会显示聊天记录。")
    );
    container.appendChild(empty);
    rerenderMath();
    return;
  }

  const thread = create("div", "chat-thread");
  chat.chat_history.forEach((message) => {
    thread.appendChild(renderCoachMessage(message));
  });
  container.appendChild(thread);
  rerenderMath();
}

function renderDiagnosisMessage(message) {
  if (message.role === "student") {
    return renderChatBubble({
      role: "student",
      title: message.kind === "initial_answer" ? "学生初始回答" : "学生补充反馈",
      content: message.content,
    });
  }

  const diagnosis = message.diagnosis || {};
  const blocks = [];
  if (diagnosis.error_type) {
    blocks.push(["候选错因", localizedErrorType(diagnosis.error_type)]);
    blocks.push(["置信度", formatScore(diagnosis.confidence)]);
    blocks.push(["原因", diagnosis.reason]);
    blocks.push(["证据", diagnosis.evidence]);
    blocks.push(["推荐策略", localizedTeachingMode(diagnosis.coach_mode)]);
    blocks.push(["学生可能卡点", diagnosis.coach_trap]);
    blocks.push(["引导提示", diagnosis.coach_prompt]);
  }
  if (message.confirmation_analysis) {
    blocks.push(["确认分析", `${localizedDiagnosisStance(message.confirmation_analysis.stance)} · ${message.confirmation_analysis.reason}`]);
  }

  const bubble = renderChatBubble({
    role: "assistant",
    title: message.action === "enter_coach" ? "诊断已完成" : "诊断",
    content: message.content,
    blocks,
  });

  if (message.coach_ready || state.diagnosisFlow.can_enter_coach) {
    const actionBar = create("div", "chat-inline-actions");
    const button = create("button", "ghost-btn primary-btn", "进入引导 →");
    button.type = "button";
    button.addEventListener("click", diagnosisToCoach);
    actionBar.appendChild(button);
    bubble.appendChild(actionBar);
  }

  return bubble;
}

function renderCoachMessage(message) {
  if (message.role === "student") {
    return renderChatBubble({
      role: "student",
      title: "学生",
      content: message.content,
    });
  }

  const response = message.response || {};
  const blocks = [
    ["模式", localizedTeachingMode(response.strategy_mode)],
    ["回复质量", localizedReplyQuality(response.reply_quality)],
    ["停止原因", localizedCoachStopReason(response.stop_reason)],
    ["策略卡点", response.strategy_trap],
    ["策略提示", response.strategy_prompt],
    ["理解分析", response.reply_analysis?.reason],
  ].filter(([, value]) => value);

  return renderChatBubble({
    role: "assistant",
    title: "引导助手",
    content: message.content,
    blocks,
  });
}

function renderChatBubble({ role, title, content, blocks = [] }) {
  const wrap = create("div", `chat-row ${role}`);
  const avatar = create("div", `chat-avatar ${role}`);
  const avatarGlyph = create("span", "chat-avatar-glyph", chatAvatarGlyph(role, title));
  avatar.appendChild(avatarGlyph);
  const bubble = create("article", `chat-bubble ${role}`);
  const header = create("div", "chat-bubble-head");
  header.append(
    create("p", "section-tag", title),
    create("span", "chat-role-label", role === "student" ? "学生" : "TeachAgent")
  );
  bubble.append(
    header,
    create("div", "question-content", content || " ")
  );
  if (blocks.length) {
    const blockWrap = create("div", "chat-blocks");
    blocks.forEach(([label, value]) => {
      if (!value) return;
      const card = create("div", "chat-mini-block");
      card.append(create("h5", null, label), create("p", "content-value", String(value)));
      blockWrap.appendChild(card);
    });
    bubble.appendChild(blockWrap);
  }
  if (role === "student") {
    wrap.append(bubble, avatar);
  } else {
    wrap.append(avatar, bubble);
  }
  return wrap;
}

function chatAvatarGlyph(role, title) {
  if (role === "student") return "学";
  if (String(title).includes("引导")) return "导";
  return "诊";
}

function renderWaitingOverlay(container, active, text) {
  if (!active) return;
  const overlay = create("div", "waiting-overlay");
  const spinner = create("div", "waiting-spinner");
  const label = create("p", "waiting-label", text);
  overlay.append(spinner, label);
  container.appendChild(overlay);
}

function setLoading(kind, active, button) {
  state.loading[kind] = active;
  if (!button) return;
  button.disabled = active;
  button.classList.toggle("waiting", active);
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent || "";
  }
  button.textContent = active ? "等待中..." : button.dataset.defaultLabel;
  if (kind === "diagnosis") {
    renderDiagnosisOutput();
  } else if (kind === "coach") {
    renderCoachOutput();
  }
}

function syncLivePanels() {
  const diagnosisSetupPanel = $("diagnosisSetupPanel");
  const diagnosisLivePanel = $("diagnosisLivePanel");
  const diagnosisLiveHint = $("diagnosisLiveHint");
  if (diagnosisSetupPanel) {
    diagnosisSetupPanel.style.display = "block";
  }
  if (diagnosisLivePanel) {
    diagnosisLivePanel.style.display = state.diagnosisFlow.chat_history?.length ? "block" : "none";
  }
  if (diagnosisLiveHint) {
    diagnosisLiveHint.textContent = state.diagnosisFlow.chat_history?.length ? diagnosisHintText() : "";
  }

  const coachActive = Boolean(state.coachChat.active);
  const coachSetupPanel = $("coachSetupPanel");
  const coachLivePanel = $("coachLivePanel");
  const coachLiveHint = $("coachLiveHint");
  if (coachSetupPanel) {
    coachSetupPanel.style.display = coachActive ? "none" : "block";
  }
  if (coachLivePanel) {
    coachLivePanel.style.display = coachActive ? "block" : "none";
  }
  if (coachLiveHint) {
    coachLiveHint.textContent = coachActive ? coachHintText() : "";
  }

  if ($("diagnosisToCoachBtn")) {
    $("diagnosisToCoachBtn").disabled = !state.diagnosisFlow.can_enter_coach || state.loading.diagnosis;
  }
  if ($("continueDiagnosisBtn")) {
    $("continueDiagnosisBtn").disabled = !state.diagnosisFlow.can_continue || state.loading.diagnosis;
  }
  if ($("continueCoachBtn")) {
    $("continueCoachBtn").disabled = state.coachChat.done || state.loading.coach;
  }
  if ($("resumeCoachBtn")) {
    $("resumeCoachBtn").style.display = state.coachChat.done ? "block" : "none";
    $("resumeCoachBtn").disabled = !state.coachChat.done || state.loading.coach;
  }
  if ($("coachToWrongbookBtn")) {
    $("coachToWrongbookBtn").disabled = state.loading.coach;
  }
}

function diagnosisHintText() {
  if (state.diagnosisFlow.can_continue) {
    return "如果判断不对，直接改。";
  }
  if (state.diagnosisFlow.can_enter_coach) {
    return "结果已经出来了，可以去引导。";
  }
  return "当前没有诊断会话。";
}

function coachHintText() {
  if (state.coachChat.done) {
    return `这一轮已结束：${localizedCoachStopReason(state.coachChat.stop_reason)}。`;
  }
  return `第 ${state.coachChat.turn_index}/${state.coachChat.max_turns} 轮，继续回答。`;
}

function buildTreeIndex(treeRoots) {
  const lookup = {};
  const parentLookup = {};

  function visit(node, parentId = null) {
    if (!node || !node.node_id) return;
    lookup[node.node_id] = node;
    parentLookup[node.node_id] = parentId;
    (node.children || []).forEach((child) => visit(child, node.node_id));
  }

  treeRoots.forEach((node) => visit(node, null));
  return {
    lookup,
    parentLookup,
    roots: treeRoots,
  };
}

function getTreePath(nodeId) {
  if (!nodeId || !state.treeLookup[nodeId]) return [];
  const path = [];
  let currentId = nodeId;
  while (currentId && state.treeLookup[currentId]) {
    path.push(state.treeLookup[currentId]);
    currentId = state.treeParentLookup[currentId];
  }
  return path.reverse();
}

function getWrongbookPath(nodeId) {
  if (!nodeId || !state.wrongbookLookup[nodeId]) return [];
  const path = [];
  let currentId = nodeId;
  while (currentId && state.wrongbookLookup[currentId]) {
    path.push(state.wrongbookLookup[currentId]);
    currentId = state.wrongbookParentLookup[currentId];
  }
  return path.reverse();
}

function ensureWrongbookExpandedPath(nodeId) {
  if (!nodeId || !state.wrongbookLookup[nodeId]) return;
  const path = getWrongbookPath(nodeId);
  path.slice(0, -1).forEach((node) => {
    state.wrongbookExpandedNodeIds.add(node.node_id);
  });
}

function toggleWrongbookNode(nodeId) {
  if (!nodeId) return;
  if (state.wrongbookExpandedNodeIds.has(nodeId)) {
    state.wrongbookExpandedNodeIds.delete(nodeId);
  } else {
    state.wrongbookExpandedNodeIds.add(nodeId);
  }
  renderWrongbook();
}

function renderTree() {
  const root = $("treeRoot");
  const detailPanel = $("treeDetailPanel");
  if (!root) return;
  root.innerHTML = "";
  if (detailPanel) {
    detailPanel.innerHTML = "";
    detailPanel.classList.remove("empty");
  }
  if (!state.tree || !state.tree.tree) {
    root.appendChild(create("p", "memory-note", "树数据尚未加载。"));
    return;
  }
  $("treeMeta").textContent = `自定义节点 ${state.tree.custom_node_count} 个 · 错题笔记 ${state.tree.note_count} 条`;
  const pathNodes = getTreePath(state.selectedTreeNodeId);
  const columns = [];
  columns.push({
    key: "roots",
    title: "总目录",
    meta: `顶层节点 ${state.treeRoots.length} 个`,
    nodes: state.treeRoots,
    activeNodeId: pathNodes[0]?.node_id || null,
  });
  pathNodes.forEach((node, index) => {
    if (!(node.children || []).length) return;
    columns.push({
      key: node.node_id,
      title: node.name || node.node_id,
      meta: `${node.children.length} 个下级节点`,
      nodes: node.children,
      activeNodeId: pathNodes[index + 1]?.node_id || null,
    });
  });
  columns.forEach((column) => {
    root.appendChild(renderTreeColumn(column));
  });
  renderTreeDetailPanel(pathNodes[pathNodes.length - 1] || null);
  if (state.activeTab === "tree") {
    window.requestAnimationFrame(() => {
      const activeEntry = root.querySelector(".tree-entry.active");
      if (!activeEntry) return;
      try {
        activeEntry.scrollIntoView({
          block: "nearest",
          inline: "nearest",
        });
      } catch (error) {
        console.warn("tree scrollIntoView failed", error);
      }
    });
  }
  rerenderMath();
}

function selectTreeParent() {
  if (!state.selectedTreeNodeId) return;
  const parentId = state.treeParentLookup[state.selectedTreeNodeId];
  if (!parentId || !state.treeLookup[parentId]) {
    showStatus("已经在最上一级");
    return;
  }
  state.selectedTreeNodeId = parentId;
  if ($("treeParentNodeId")) {
    $("treeParentNodeId").value = parentId;
  }
  renderTree();
}

function selectTreeRoot() {
  const rootId = state.treeRoots[0]?.node_id;
  if (!rootId) return;
  state.selectedTreeNodeId = rootId;
  if ($("treeParentNodeId")) {
    $("treeParentNodeId").value = rootId;
  }
  renderTree();
}

function selectWrongbookParent() {
  if (!state.selectedWrongbookNodeId) return;
  const parentId = state.wrongbookParentLookup[state.selectedWrongbookNodeId];
  if (!parentId || !state.wrongbookLookup[parentId]) {
    showStatus("已经在最上一级");
    return;
  }
  state.selectedWrongbookNodeId = parentId;
  $("wrongbookPrimaryNodeId").value = parentId;
  ensureWrongbookExpandedPath(parentId);
  renderWrongbook();
}

function selectWrongbookRoot() {
  const rootId = state.wrongbookRoots[0]?.node_id;
  if (!rootId) return;
  state.selectedWrongbookNodeId = rootId;
  $("wrongbookPrimaryNodeId").value = rootId;
  ensureWrongbookExpandedPath(rootId);
  renderWrongbook();
}

function renderTreeColumn(column) {
  const section = create("section", "tree-column");
  const head = create("div", "tree-column-head");
  head.append(
    create("p", "section-tag", "目录列"),
    create("h3", "tree-column-title", column.title),
    create("p", "tree-column-meta", column.meta)
  );
  section.appendChild(head);

  const list = create("div", "tree-column-list");
  column.nodes.forEach((node) => {
    const button = create("button", `tree-entry${column.activeNodeId === node.node_id ? " active" : ""}`);
    button.type = "button";
    button.addEventListener("click", () => {
      state.selectedTreeNodeId = node.node_id;
      $("treeParentNodeId").value = node.node_id;
      renderTree();
    });

    const top = create("div", "tree-entry-top");
    top.append(
      create("div", "tree-entry-name", node.name || node.node_id),
      create("span", "tree-entry-kind", node.is_leaf ? "叶子" : "目录")
    );

    const metaParts = [];
    metaParts.push(localizedNodeKind(node.node_kind || (node.is_leaf ? "concept" : "unknown")));
    metaParts.push(`下级 ${(node.children || []).length} 个`);
    metaParts.push(`挂题 ${(node.linked_questions || []).length} 道`);
    if (node.is_custom) {
      metaParts.push("自定义");
    }

    button.append(
      top,
      create("p", "tree-entry-meta", metaParts.join(" · ")),
      create("div", "tree-entry-path", node.node_id)
    );
    list.appendChild(button);
  });
  section.appendChild(list);
  return section;
}

function renderTreeDetailPanel(node) {
  const panel = $("treeDetailPanel");
  if (!panel) return;
  panel.innerHTML = "";

  if (!node) {
    panel.classList.add("empty");
    const empty = create("div", "tree-empty-card");
    empty.append(
      create("p", "section-tag", "知识点详情"),
      create("h3", "card-title", "先从左侧目录选择一个知识点"),
      create("p", "memory-note", "选择后，这里会显示路径、常见错误、挂载题目和笔记入口。")
    );
    panel.appendChild(empty);
    return;
  }

  panel.classList.remove("empty");
  const card = create("section", "tree-detail-card");
  card.append(
    create("p", "section-tag", node.is_custom ? "自定义节点" : "知识点详情"),
    create("h3", "card-title", node.name || node.node_id),
    create("p", "meta-text", `知识点编号：${node.node_id}`),
    create("p", "meta-text", `路径：${node.path_text || (node.path || []).join(" > ") || "-"}`),
    create(
      "p",
      "meta-text",
      `类型：${localizedNodeKind(node.node_kind)} · 叶子：${node.is_leaf ? "是" : "否"} · 下级节点：${(node.children || []).length}`
    )
  );

  if (node.aliases && node.aliases.length) {
    card.appendChild(create("p", "memory-note", `别名：${node.aliases.join("，")}`));
  }
  if (node.common_errors && node.common_errors.length) {
    card.appendChild(create("p", "memory-note", `常见错误：${node.common_errors.join("；")}`));
  }

  const actions = create("div", "tree-detail-actions");
  const useParentBtn = create("button", "ghost-btn", "作为新节点父节点");
  useParentBtn.type = "button";
  useParentBtn.addEventListener("click", () => {
    $("treeParentNodeId").value = node.node_id;
    showStatus("已填入父节点");
  });
  const openChildBtn = create(
    "button",
    "ghost-btn",
    (node.children || []).length ? "继续展开下一级" : "这是当前末级节点"
  );
  openChildBtn.type = "button";
  openChildBtn.disabled = !(node.children || []).length;
  openChildBtn.addEventListener("click", () => {
    const firstChild = node.children?.[0];
    if (!firstChild) return;
    state.selectedTreeNodeId = firstChild.node_id;
    $("treeParentNodeId").value = firstChild.node_id;
    renderTree();
  });
  actions.append(useParentBtn, openChildBtn);
  card.appendChild(actions);
  panel.appendChild(card);

  const board = create("section", "tree-detail-card");
  board.append(
    create("p", "section-tag", "挂载题目"),
    create("h3", "card-title", `已绑定 ${node.linked_questions.length} 道题`)
  );
  if (!node.linked_questions.length) {
    board.appendChild(create("p", "memory-note", "当前这个知识点下还没有挂载题目。"));
  } else {
    const list = create("div", "tree-question-list");
    node.linked_questions.forEach((question) => {
      list.appendChild(renderWrongQuestionItem(question));
    });
    board.appendChild(list);
  }
  panel.appendChild(board);
}

function renderWrongbook() {
  const root = $("wrongbookTreeRoot");
  const detailPanel = $("wrongbookDetailPanel");
  if (!root || !detailPanel) return;
  root.innerHTML = "";
  detailPanel.innerHTML = "";

  if (!state.wrongbook || !state.wrongbook.tree) {
    root.appendChild(create("p", "memory-note", "错题本数据尚未加载。"));
    return;
  }

  $("wrongbookMeta").textContent =
    `当前学生 ${state.student.student_id || "-"} · 完整知识点 ${state.wrongbook.node_count} 个 · 已挂题节点 ${state.wrongbook.active_wrong_node_count} 个 · 错题 ${state.wrongbook.question_count} 道`;
  ensureWrongbookExpandedPath(state.selectedWrongbookNodeId);

  const treeShell = create("div", "wrongbook-folder-tree");
  state.wrongbookRoots.forEach((node) => {
    treeShell.appendChild(renderWrongbookFolderNode(node, 0));
  });
  root.appendChild(treeShell);
  renderWrongbookDetailPanel(state.wrongbookLookup[state.selectedWrongbookNodeId] || null);
  rerenderMath();
}

function renderWrongbookFolderNode(node, depth) {
  const wrap = create("div", "wrongbook-folder-node");
  wrap.style.setProperty("--folder-depth", String(depth));

  const hasChildren = Boolean(node.children && node.children.length);
  const expanded = state.wrongbookExpandedNodeIds.has(node.node_id);
  const row = create(
    "button",
    `wrongbook-folder-row${state.selectedWrongbookNodeId === node.node_id ? " active" : ""}${node.question_count > 0 ? " has-questions" : ""}`
  );
  row.type = "button";
  row.addEventListener("click", () => {
    if (hasChildren) {
      if (expanded) {
        state.wrongbookExpandedNodeIds.delete(node.node_id);
      } else {
        state.wrongbookExpandedNodeIds.add(node.node_id);
      }
    }
    state.selectedWrongbookNodeId = node.node_id;
    $("wrongbookPrimaryNodeId").value = node.node_id;
    $("wrongbookParentNodeId").value = node.node_id;
    ensureWrongbookExpandedPath(node.node_id);
    renderWrongbook();
  });

  const branchToggle = create("span", `wrongbook-folder-toggle${hasChildren ? "" : " leaf"}`, hasChildren ? (expanded ? "收" : "展") : "");

  const icon = create(
    "span",
    "wrongbook-folder-icon",
    hasChildren ? (expanded ? "📂" : "📁") : "📄"
  );

  const labelWrap = create("div", "wrongbook-folder-label");
  labelWrap.append(
    create("div", "wrongbook-folder-name", node.name || node.node_id),
    create(
      "div",
      "wrongbook-folder-meta",
      `本点 ${node.direct_question_count || 0} · 合计 ${node.question_count || 0}`
    )
  );

  row.append(branchToggle, icon, labelWrap);
  wrap.appendChild(row);

  if (hasChildren && expanded) {
    const children = create("div", "wrongbook-folder-children");
    node.children.forEach((child) => {
      children.appendChild(renderWrongbookFolderNode(child, depth + 1));
    });
    wrap.appendChild(children);
  }
  return wrap;
}

function renderWrongbookDetailPanel(node) {
  const panel = $("wrongbookDetailPanel");
  if (!panel) return;
  panel.innerHTML = "";

  if (!node) {
    const empty = create("div", "tree-empty-card");
    empty.append(
      create("p", "section-tag", "错题本详情"),
      create("h3", "card-title", "先选一个知识点"),
      create("p", "memory-note", "右边会显示这个点下的题。")
    );
    panel.appendChild(empty);
    return;
  }

  const head = create("section", "tree-detail-card");
  head.append(
    create("p", "section-tag", node.is_custom ? "自定义知识点" : "知识点"),
    create("h3", "card-title", node.name || node.node_id),
    create("p", "meta-text", `知识点编号：${node.node_id}`),
    create("p", "meta-text", `路径：${node.path_text || (node.path || []).join(" > ") || "-"}`),
    create("p", "meta-text", `当前知识点直挂 ${node.direct_question_count || 0} 道 · 整个分支合计 ${node.question_count || 0} 道`)
  );
  if (node.common_errors && node.common_errors.length) {
    head.appendChild(create("p", "memory-note", `常见错误：${node.common_errors.join("；")}`));
  }
  const actions = create("div", "tree-detail-actions");
  const usePrimaryBtn = create("button", "ghost-btn", "作为错题主知识点");
  usePrimaryBtn.type = "button";
  usePrimaryBtn.addEventListener("click", () => {
    $("wrongbookPrimaryNodeId").value = node.node_id;
    showStatus("已填入主知识点");
  });
  const useParentBtn = create("button", "ghost-btn", "作为新节点父节点");
  useParentBtn.type = "button";
  useParentBtn.addEventListener("click", () => {
    $("wrongbookParentNodeId").value = node.node_id;
    showStatus("已填入父节点");
  });
  actions.append(usePrimaryBtn, useParentBtn);
  head.appendChild(actions);
  panel.appendChild(head);

  const board = create("section", "tree-detail-card wrongbook-board");
  board.append(
    create("p", "section-tag", "错题列表"),
    create("h3", "card-title", `共 ${node.linked_questions.length} 道题`)
  );
  if (!node.linked_questions.length) {
    board.appendChild(create("p", "memory-note", "这里还没有题，可以直接添加。"));
  } else {
    const list = create("div", "wrongbook-question-list");
    node.linked_questions.forEach((question) => {
      list.appendChild(renderWrongbookQuestionItem(question));
    });
    board.appendChild(list);
  }
  panel.appendChild(board);
}

function renderWrongbookQuestionItem(question) {
  const item = create("article", "wrongbook-question-item");
  const payload = question.question_payload || {};
  const labels = [];
  if (payload.question_type) labels.push(payload.question_type);
  labels.push(`上次结果：${localizedQuestionResult(question.last_result)}`);
  labels.push(`来源：${localizedWrongbookSourceType(question.source_type)}`);
  if (question.is_direct_link) {
    labels.push("本点直挂");
  } else {
    labels.push(`来自子点 ${question.linked_via_node_ids?.join("，") || "-"}`);
  }
  item.append(
    create("p", "section-tag", question.question_id),
    create("h4", "card-title", payload.source_name || question.priority_note || "错题"),
    create("p", "question-meta", labels.join(" · ")),
    create("div", "question-content", payload.stem || "暂无题干")
  );
  if (payload.student_answer) {
    item.appendChild(create("p", "meta-text", `学生答案：${payload.student_answer}`));
  }
  if (question.priority_note) {
    item.appendChild(create("p", "memory-note", `优先提示：${question.priority_note}`));
  }
  if (payload.source_chapter) {
    item.appendChild(create("p", "meta-text", `来源章节：${payload.source_chapter}`));
  }
  if (question.primary_node_ids?.length) {
    item.appendChild(create("p", "meta-text", `主知识点：${question.primary_node_ids.join("，")}`));
  }
  if (question.secondary_node_ids?.length) {
    item.appendChild(create("p", "meta-text", `辅助知识点：${question.secondary_node_ids.join("，")}`));
  }

  const answer = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "展开答案与解析";
  answer.appendChild(summary);
  answer.appendChild(create("div", "question-content", `标准答案：${payload.correct_answer || "暂无"}`));
  answer.appendChild(create("div", "question-content", `参考解析：${payload.solution_text || "暂无"}`));
  item.appendChild(answer);

  const noteBox = create("textarea", "note-box");
  noteBox.value = question.note || "";
  noteBox.placeholder = "记录错因、补充思路、复盘总结";
  const saveBtn = create("button", "ghost-btn", "保存笔记");
  saveBtn.type = "button";
  saveBtn.addEventListener("click", async () => {
    await saveWrongbookNote(question.question_id, noteBox.value);
  });
  item.append(noteBox, saveBtn);
  return item;
}

function renderWrongQuestionItem(question) {
  const item = create("div", "wrong-question-item");
  const payload = question.question_payload || {};
  item.append(
    create("p", "section-tag", question.question_id),
    create("p", "meta-text", `${payload.question_type || "题型未标注"} · 上次结果：${localizedQuestionResult(question.last_result)}`),
    create("div", "question-content", payload.stem || "暂无题干")
  );

  const answer = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "展开答案与解析";
  answer.appendChild(summary);
  answer.appendChild(create("div", "question-content", `答案：${payload.correct_answer || "暂无"}`));
  answer.appendChild(create("div", "question-content", `解析：${payload.solution_text || "暂无"}`));
  item.appendChild(answer);

  const noteBox = create("textarea", "note-box");
  noteBox.value = question.note || "";
  noteBox.placeholder = "在这里记录这道题的错因、补充思路或复盘笔记";
  const saveBtn = create("button", "ghost-btn", "保存笔记");
  saveBtn.type = "button";
  saveBtn.addEventListener("click", async () => {
    await saveTreeNote(question.question_id, noteBox.value);
  });
  item.append(noteBox, saveBtn);
  return item;
}

function renderLinkedCards(cards) {
  const wrap = create("div", "linked-card-stack");
  if (!cards.length) {
    const empty = create("section", "mini-card");
    empty.append(
      create("p", "section-tag", "关联知识点"),
      create("h4", "card-title", "当前没有补充卡片")
    );
    wrap.appendChild(empty);
    return wrap;
  }

  cards.forEach((cardData) => {
    const card = create("section", "mini-card");
    card.append(
      create("p", "section-tag", "关联知识点"),
      create("h4", "card-title", cardData.title || cardData.node_id),
      create("p", "meta-text", `${localizedCardType(cardData.card_type)} · ${localizedNodeKind(cardData.node_kind)}`)
    );
    if (cardData.review_cue) {
      card.appendChild(create("p", "memory-note", cardData.review_cue));
    }
    wrap.appendChild(card);
  });
  return wrap;
}

function renderActionRow(actions) {
  const row = create("div", "action-row");
  actions.forEach((action) => {
    const button = create("button", actionButtonClass(action), action.label || action.action);
    button.type = "button";
    if (action.action === "reveal_answer") {
      button.addEventListener("click", () => {});
      button.disabled = true;
      button.style.opacity = "0.45";
      button.textContent = "答案由上方按钮展开";
    } else {
      button.addEventListener("click", async () => {
        await applyAction(action);
      });
    }
    row.appendChild(button);
  });
  return row;
}

function normalizePrimaryActions(actions) {
  return actions.map((action) => {
    if (action.action === "node_mastered_well") {
      return { ...action, variant: "primary" };
    }
    if (action.action === "skip_temporarily") {
      return { ...action, variant: "warn" };
    }
    return action;
  });
}

function actionButtonClass(action) {
  const base = "action-btn";
  const variant = action.variant
    || (action.action === "review_result" && action.result === "wrong" ? "warn" : "")
    || (action.action === "node_mastered_well" ? "primary" : "");
  return variant ? `${base} ${variant}` : base;
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(3);
}

function joinValue(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.join("\n");
  return String(value);
}

function modeLabel(mode) {
  const item = MODES.find((entry) => entry.id === mode);
  return item ? item.label : mode;
}

function showStatus(text) {
  let bar = document.querySelector(".status-bar");
  if (!bar) {
    bar = create("div", "status-bar");
    document.body.appendChild(bar);
  }
  bar.textContent = text;
  bar.classList.add("show");
  window.clearTimeout(showStatus._timer);
  showStatus._timer = window.setTimeout(() => {
    bar.classList.remove("show");
  }, 1800);
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function render() {
  if (!state.dashboard) return;
  renderStudentCard();
  renderStudentDirectory();
  renderModeSwitch();
  renderQuickStartCard();
  renderSessionSummary();
  renderMemoryCard();
  renderBundles();
  renderDiagnosisOutput();
  renderCoachOutput();
  syncPanels();
  rerenderMath();
}

async function bootstrap() {
  $("refreshBtn").addEventListener("click", loadDashboard);
  $("resetBtn").addEventListener("click", resetSession);
  $("switchStudentBtn").addEventListener("click", switchStudent);
  $("studentIdInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      switchStudent();
    }
  });
  $("importTarget").addEventListener("change", (event) => {
    populateImportFieldModes(event.target.value);
  });
  $("importOcrBtn").addEventListener("click", runOcrImport);
  $("importQuestionOcrBtn").addEventListener("click", () => runFieldOcrImport("question"));
  $("importAnswerOcrBtn").addEventListener("click", () => runFieldOcrImport("answer"));
  $("importSolutionOcrBtn").addEventListener("click", () => runFieldOcrImport("solution"));
  $("runDiagnosisBtn").addEventListener("click", runDiagnosis);
  $("continueDiagnosisBtn").addEventListener("click", continueDiagnosis);
  $("cancelDiagnosisBtn").addEventListener("click", cancelDiagnosis);
  $("diagnosisToCoachBtn").addEventListener("click", diagnosisToCoach);
  $("diagnosisToWrongbookBtn").addEventListener("click", moveDiagnosisToWrongbook);
  $("runCoachBtn").addEventListener("click", runCoach);
  $("continueCoachBtn").addEventListener("click", continueCoach);
  $("resumeCoachBtn").addEventListener("click", resumeCoach);
  $("coachToWrongbookBtn").addEventListener("click", moveCoachToWrongbook);
  $("cancelCoachBtn").addEventListener("click", cancelCoach);
  $("createWrongbookNodeBtn").addEventListener("click", createWrongbookNode);
  $("createWrongbookQuestionBtn").addEventListener("click", createWrongbookQuestion);
  $("wrongbookBackBtn").addEventListener("click", selectWrongbookParent);
  $("wrongbookRootBtn").addEventListener("click", selectWrongbookRoot);
  setupOcrDropzone("importOcrDropzone", "importOcrFile", "importOcrFileName");
  setupOcrDropzone("importQuestionOcrDropzone", "importQuestionOcrFile", "importQuestionOcrFileName");
  setupOcrDropzone("importAnswerOcrDropzone", "importAnswerOcrFile", "importAnswerOcrFileName");
  setupOcrDropzone("importSolutionOcrDropzone", "importSolutionOcrFile", "importSolutionOcrFileName");
  populateImportFieldModes($("importTarget")?.value || "wrongbook");
  await loadDashboard();
  await Promise.all([loadTree(), loadWrongbook(), loadDiagnosisState(), loadCoachState(), loadStudentDirectory()]);
  render();
  renderDiagnosisOutput();
  renderCoachOutput();
  renderWrongbook();
  syncLivePanels();
}

bootstrap().catch((error) => {
  console.error(error);
  showStatus(`加载失败：${error.message}`);
});
