package os.opos.launcher;

import android.animation.AnimatorListenerAdapter;
import android.animation.LayoutTransition;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.ClipData;
import android.content.ClipDescription;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Point;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Rect;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.text.Editable;
import android.text.Layout;
import android.text.SpannableString;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.TextUtils;
import android.text.TextWatcher;
import android.text.style.CharacterStyle;
import android.text.style.ForegroundColorSpan;
import android.text.style.AbsoluteSizeSpan;
import android.text.style.TypefaceSpan;
import android.text.style.UpdateAppearance;
import android.util.TypedValue;
import android.view.DragEvent;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Choreographer;
import android.view.View;
import android.widget.RadioButton;
import android.view.TouchDelegate;
import android.view.VelocityTracker;
import android.view.ViewConfiguration;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.Window;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.animation.LinearInterpolator;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.provider.Settings;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.text.DateFormat;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import os.opos.launcher.SettingsPcState.Connection;

/** Native models screen. The phone-local OPOS service owns answers, trust and link state. */
public final class MainActivity extends Activity {
    private static final long LINK_STATUS_HOLD_MS = 3500;
    private static final int TIMING_CARD_MIN_DP = 96;
    private static final int BACK_ISSUE_TIMING_MIN_DP = 140;
    private static final int BACK_ISSUE_ARCHIVE_MIN_DP = 200;
    private static final int BACK_ISSUE_SUMMARY_MIN_DP = 100;
    private static final String PREF_UNRESOLVED_ASK = "ask_post_unresolved";
    private static volatile boolean resumed;
    /** Kept only across a layout-family recreate, so a fold does not blank the newspaper. */
    private static JSONObject foldSnapshot;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final AiClient client = new AiClient();
    private final AskRecoveryPolicy askRecovery = new AskRecoveryPolicy();
    private final AnswerTimingPolicy answerTiming = new AnswerTimingPolicy();
    private final Runnable poll = this::refresh;
    private final Runnable coverResultsCheck = this::ensureCoverResultsArea;
    private final Map<String, Long> answerStarts = new HashMap<>();
    private final Map<TextView, String> pcLabelledViews = new java.util.WeakHashMap<>();
    private final Map<TextView, SummaryPaintPolicy.Paint> summaryPaints = new java.util.WeakHashMap<>();
    private Typography typography;
    private UiSettings uiSettings;
    private UiPalette palette = new UiPalette(UiPalette.Theme.DARK);
    private Dialog settingsDialog;
    private Runnable pendingNotesDrag;
    private float notesDragDownX, notesDragDownY;
    private boolean notesDragActive;
    private String suppressArticleClick;
    private final Map<String, Long> answerDurations = new HashMap<>();
    private final Map<String, Long> answerFinishedAt = new HashMap<>();
    private final Map<String, String> latestRequestIds = new HashMap<>();
    private final Map<String, String> previousAnswerIds = new HashMap<>();
    private final Map<String, PaneViews> paneViews = new LinkedHashMap<>();
    // Per-lane Retry: stall detection, one button per card, and a rebind after an uncertain POST.
    private final LaneHealth laneHealth = new LaneHealth();
    private final Map<String, Button> laneRetryButtons = new HashMap<>();
    private final Map<String, Boolean> laneRetryReady = new HashMap<>();
    private final Map<String, String> laneRetryRebind = new HashMap<>();
    private final Map<View, NewspaperLayoutDecision.RevealOnce> revealStates = new IdentityHashMap<>();
    private final List<String> paneOrder = new ArrayList<>();
    private final List<String> displayedPanes = new ArrayList<>();
    private final MenuState menuState = new MenuState();
    private final Set<String> latestRequestedPanes = new HashSet<>();
    private final BroadcastReceiver cableReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!LinkWatcherService.ACTION_CABLE_CHANGED.equals(intent.getAction())) return;
            Boolean observed = intent.hasExtra(LinkWatcherService.EXTRA_CONNECTED)
                    ? intent.getBooleanExtra(LinkWatcherService.EXTRA_CONNECTED, false)
                    : LinkWatcherService.cableConnected(context);
            if (observed == null) return;
            awaitingReplugSnapshot = observed;
            cableConnected = observed;
            if (!observed) {
                lastGoodPcAtMs = 0;
                lastPcLiveAtMs = 0;
                pausedAfterFreshSnapshot = false;
                for (String pane : paneNames(snapshot)) {
                    if (!PaneKeys.pc(pane)) continue;
                    JSONObject answer = answerOf(snapshot, pane);
                    if (open(answer)) answerTiming.observe(pane,
                            answer.optString("state"), answer.optString("id"), observed,
                            SystemClock.elapsedRealtime());
                }
            }
            renderStatus();
            renderAnswers();
            updateButtons();
            schedule(0);
        }
    };

    private View screen, pairing, pairingClosed;
    private ScrollView resultsScroll, summaryScroll;
    private LinearLayout header, answers, leftColumn, rightColumn, summaryCard, summaryRow;
    private TextView bigMasthead;
    private LinearLayout mastheadBlock;
    private int expandedMastheadHeightPx;
    private LinearLayout columns;
    private LinearLayout timingCard, notesCard, notesDock, notesTab, bottomDock;
    private List<NewspaperSummary.Lane> tonightLanes;
    /** Race headline under the TONIGHT rows ("Fastest so far: MacBook · 28.4 s"). */
    private TextView tonightLeader;
    /** Design lab (experimental, Settings): a monospace view above the lanes. Off by default. */
    private TextView labView;
    private int labTick;
    private final Runnable labTicker = this::tickLab;
    /** One animator draws every on-screen live line; text is never reset on a frame. */
    private ValueAnimator workingAnimator;
    private final ArrayList<PaneViews> animatedWorking = new ArrayList<>();
    private final Rect workingViewport = new Rect();
    private final Rect workingBounds = new Rect();
    private TextView heatMeter, batteryNotice;
    private final BroadcastReceiver batteryReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            showBattery(intent);
        }
    };
    private TextView cableBannerTitle, cableBannerBody;
    private LinearLayout cableBanner;
    private LinearLayout deviceBand, devicePhone, deviceComputer;
    private TextView devicePhoneKicker, devicePhoneName, deviceComputerKicker,
            deviceComputerName, deviceLink;
    private DeviceLayoutPolicy.LinkState deviceLinkState = DeviceLayoutPolicy.LinkState.WAITING;
    private PowerManager.OnThermalStatusChangedListener heatListener;
    private boolean heatRegistered;
    private int heatStatus = -1;
    private LinearLayout settingsLabList;
    private TextView notesTabLabel;
    private NotesSheet.State notesSheetState = NotesSheet.State.COLLAPSED;
    private boolean summaryExpanded;
    private ValueAnimator notesSheetAnimator;
    private Choreographer.FrameCallback notesSpringCallback;
    private float notesSpringPos;
    private float notesSpringVel;
    private float notesSpringTarget;
    private long notesSpringLastFrameNs;
    private int insetLeft, insetTop, insetRight, insetBottom;
    private boolean notesSheetDragging;
    private boolean notesConfirming;
    private float notesSheetDownY;
    private int notesSheetStartHeight;
    private VelocityTracker notesSheetVelocity;
    private TextView smallMasthead, compactLaneStatus;
    private EditText prompt;
    private LinedNotesEditText notes;
    private Button send, stop, retry, reconnect, resetAsk, info, settings, allow, deny, reopen;
    private TextView resetAskCopy;
    private TextView status, error, question, pairingText, pairingCode, pairingCountdown;
    private int pairingSeconds = -1;
    private int lastPairingSeconds = -1;
    private String lastPairingCode = "", rejectedPairingCode = "";
    private boolean pairingTimedOut;
    private String pairingActionMessage = "";
    private boolean pairingActionError;
    private int lastPairingProblem;
    private TextView phoneState, phoneAnswer, gpuHeading, gpuState, gpuAnswer;
    private LinearLayout tonightRows;
    private TextView tonightCount, tonightProvenance, tonightTiming, summaryHeading, summaryText,
            expandedState, expandedWorkingCount, expandedAnswer,
            expandedStatus, expandedTitle, expandedByline;
    private final WorkingSpans expandedWorkingSpans = new WorkingSpans();
    private boolean expandedWorkingAnimated;
    private ScrollView expandedScroll;
    private NewspaperLayoutDecision.FollowTail expandedFollow;
    private boolean expandedTouching;
    private boolean expandedWasPaused;
    private float expandedTouchY;
    private boolean expandedUserScrolled, expandedProgrammaticScroll, expandedWasDone;
    private Dialog articleDialog;
    private String expandedPane;
    private long questionStartedAtMs;
    private long overallElapsedMs = -1;
    private boolean initialRevealDone;
    private boolean reduceMotionEnabled;
    private float lastCollapseFraction = -1f;
    private JSONObject snapshot;
    private Dialog infoDialog;
    private Dialog modelSelectionDialog, historyDialog, backIssueDialog, summaryDialog;
    private TextView fullSummaryText;
    private Dialog quitProgressDialog;
    private PopupWindow menuPopup;
    private LaneSelection laneSelection;
    private HistoryStore historyStore;
    private LinearLayout modelRows;
    private LinearLayout historyRows;
    private TextView modelSelectionNotice;
    private final List<String> modelRowPanes = new ArrayList<>();
    private final Map<String, TextView> modelReadyHints = new HashMap<>();
    private final Map<String, TextView> modelToggles = new HashMap<>();
    private final Map<String, TextView> modelLabels = new HashMap<>();
    private final Map<String, TextView> modelMetaViews = new HashMap<>();
    private boolean displayPinned, quitting, stopWaitingForId;
    private boolean foldRestored;
    private String archivedIssueId = "";
    private String pendingRefreshSourceId = "";
    private String pendingRefreshQuestion = "";
    private String suppressedIssueId = "";
    private Boolean cableConnected;
    private String latestQuestion = "";
    private String lastSubmittedQuestion = "";
    private double latestAskedSeconds;
    private long lastGoodPcAtMs;
    private long lastPcLiveAtMs;
    private long latestRequestAtWallMs;
    private long latestRequestAtElapsedMs;
    private long draftRevision;
    private long clearedDraftRevision = -1;
    private String clearedDraft = "";
    private boolean visible, polling, acting, reachable, offline, compactLayout, compactImeVisible,
            landscapeLayout;
    // Galaxy Z Flip cover screen (748x720 px, about 374x360 dp): see CoverScreenPolicy.
    private CoverScreenPolicy.Mode layoutMode = CoverScreenPolicy.Mode.FULL;
    private boolean coverMode;
    private List<String> coverShown = new ArrayList<>();
    private TextView coverMore;
    private boolean recreating;
    private long coverInteractionMs;
    private boolean awaitingReplugSnapshot;
    private boolean pausedAfterFreshSnapshot;
    private PendingAsk pendingAsk;
    private boolean pairingPending;

    private static final class PendingAsk {
        final JSONObject before;
        final JSONArray requested;
        final String question, draft;
        final long startedAtMs, submittedAtWallMs, draftRevision;
        final boolean retrying;
        final AskRecoveryPolicy.Attempt attempt;
        boolean bound;

        PendingAsk(JSONObject before, JSONArray requested, String question,
                   long startedAtMs, long submittedAtWallMs, boolean retrying,
                   String draft, long draftRevision) {
            this.before = before;
            this.requested = requested;
            this.question = question;
            this.startedAtMs = startedAtMs;
            this.submittedAtWallMs = submittedAtWallMs;
            this.retrying = retrying;
            this.draft = draft;
            this.draftRevision = draftRevision;
            List<String> panes = new ArrayList<>();
            for (int i = 0; i < requested.length(); i++) panes.add(requested.optString(i));
            this.attempt = new AskRecoveryPolicy.Attempt(
                    question, panes, askAnswers(before, requested));
        }
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        ComputerWords.restore(getPreferences(MODE_PRIVATE).getString("computer_noun", ComputerWords.COMPUTER));
        setContentView(R.layout.models);
        SharedPreferences preferences = getPreferences(MODE_PRIVATE);
        pcLabelStatic(findViewById(android.R.id.content), new int[][]{
                {R.id.pairing_disclosure, R.string.pairing_disclosure}});
        uiSettings = new UiSettings(new UiSettings.Store() {
            @Override public String get(String key, String fallback) {
                return preferences.getString(key, fallback);
            }
            @Override public void put(String key, String value) {
                preferences.edit().putString(key, value).apply();
            }
        });
        laneSelection = new LaneSelection(new LaneSelection.Store() {
            @Override public boolean contains(String key) { return preferences.contains(key); }
            @Override public boolean get(String key, boolean fallback) {
                return preferences.getBoolean(key, fallback);
            }
            @Override public void put(String key, boolean value) {
                preferences.edit().putBoolean(key, value).apply();
            }
        });
        historyStore = new HistoryStore(new HistoryStore.Store() {
            @Override public String get(String key) { return preferences.getString(key, null); }
            @Override public void update(Map<String, String> values, List<String> removals) {
                SharedPreferences.Editor edit = preferences.edit();
                for (Map.Entry<String, String> value : values.entrySet()) {
                    edit.putString(value.getKey(), value.getValue());
                }
                for (String key : removals) edit.remove(key);
                edit.apply();
            }
        });
        suppressedIssueId = preferences.getString(HistoryStore.SUPPRESSED, "");
        restoreLatestIds();
        if (preferences.getBoolean(PREF_UNRESOLVED_ASK, false)) {
            askRecovery.restoreUnknownUncertain();
        }
        screen = findViewById(R.id.screen);
        typography = new Typography(this);
        typography.useChoice(uiSettings.typography());
        palette = uiSettings.palette(systemDark());
        resultsScroll = findViewById(R.id.results_scroll);
        prompt = findViewById(R.id.prompt);
        send = findViewById(R.id.ask);
        stop = findViewById(R.id.stop);
        retry = findViewById(R.id.retry);
        reconnect = findViewById(R.id.reconnect);
        resetAsk = findViewById(R.id.reset_ask);
        resetAskCopy = findViewById(R.id.reset_ask_copy);
        info = findViewById(R.id.info);
        settings = findViewById(R.id.settings);
        allow = findViewById(R.id.allow_pc);
        deny = findViewById(R.id.deny_pc);
        reopen = findViewById(R.id.reopen_pc);
        pairing = findViewById(R.id.pairing);
        pairingClosed = findViewById(R.id.pairing_closed);
        status = findViewById(R.id.connection);
        error = findViewById(R.id.error);
        question = findViewById(R.id.question);
        pairingText = findViewById(R.id.pairing_text);
        pairingCode = findViewById(R.id.pairing_code);
        pairingCountdown = findViewById(R.id.pairing_countdown);
        phoneState = findViewById(R.id.phone_state);
        phoneAnswer = findViewById(R.id.phone_answer);
        gpuHeading = findViewById(R.id.gpu_heading);
        gpuState = findViewById(R.id.gpu_state);
        gpuAnswer = findViewById(R.id.gpu_answer);
        if (state != null) prompt.setText(state.getString("prompt", ""));
        prompt.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) {
                draftRevision++;
            }
            @Override public void afterTextChanged(Editable text) {}
        });

        setupNewspaper();
        reduceMotionEnabled = readReducedMotion();
        enableSmoothGrowth(answers);
        for (PaneViews pane : paneViews.values()) enableSmoothGrowth(pane.card);
        if (timingCard != null) enableSmoothGrowth(timingCard);
        if (notesCard != null) enableSmoothGrowth(notesCard);
        if (summaryCard != null) enableSmoothGrowth(summaryCard);
        applyScreenSize();
        applyInsets();
        applyUi();
        send.setOnClickListener(view -> askModels());
        stop.setOnClickListener(view -> stopAnswers());
        retry.setOnClickListener(view -> retryFailed());
        reconnect.setOnClickListener(view -> {
            setIfChanged(error, "");
            setMainStatus(getString(R.string.connecting));
            reconnect.setEnabled(false);
            if (!polling) refresh();
        });
        resetAsk.setOnClickListener(view -> resetAskTracking());
        info.setOnClickListener(view -> showInfo());
        settings.setOnClickListener(view -> showSettings());
        allow.setOnClickListener(view -> pairingAction("allow"));
        deny.setOnClickListener(view -> pairingAction("deny"));
        reopen.setOnClickListener(view -> sendAction(action("reopen"), null, 0, false));
        prompt.setOnEditorActionListener((view, actionId, event) -> {
            boolean sendAction = actionId == EditorInfo.IME_ACTION_SEND;
            boolean enter = event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER
                    && !event.isShiftPressed();
            if (!sendAction && !enter) return false;
            if (event == null || event.getAction() == KeyEvent.ACTION_DOWN) askModels();
            return true;
        });
        JSONObject carried = foldSnapshot;
        foldSnapshot = null;
        if (carried != null) {
            cableConnected = LinkWatcherService.cableConnected(this);
            reachable = true;
            showSnapshot(carried);
            reachable = false;
            for (PaneViews article : paneViews.values()) {
                if (open(answerOf(carried, article.pane)) && !isPausedDateline(article)) {
                    setLaneState(article.state, article.card, getString(R.string.checking));
                }
            }
            updateCompactLaneStatus();
            setMainStatus(getString(R.string.checking_connection));
            renderLinkBanner(false, hasVisiblePcWork());
            updateButtons();
            foldRestored = true;
        } else {
            showWaiting();
        }
    }

    private void applyInsets() {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            screen.setOnApplyWindowInsetsListener((view, windowInsets) -> {
                Insets bars = windowInsets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                Insets keyboard = windowInsets.getInsets(WindowInsets.Type.ime());
                Insets gestures = windowInsets.getInsets(WindowInsets.Type.systemGestures());
                insetLeft = bars.left;
                insetTop = bars.top;
                insetRight = bars.right;
                int previousInsetBottom = insetBottom;
                insetBottom = NotesSheet.dockInset(bars.bottom, gestures.bottom, keyboard.bottom);
                boolean imeVisible = windowInsets.isVisible(WindowInsets.Type.ime());
                boolean collapseSummary = landscapeLayout && imeVisible && summaryExpanded;
                if (collapseSummary) {
                    summaryExpanded = false;
                    pinSummaryBar();
                } else {
                    applyScreenBottomReserve();
                }
                if (landscapeLayout && notesSheetState != NotesSheet.State.COLLAPSED
                        && (collapseSummary || insetBottom != previousInsetBottom)) {
                    setNotesSheetState(notesSheetState, false);
                }
                if (compactLayout) setCompactKeyboardMode(imeVisible);
                return windowInsets;
            });
            screen.requestApplyInsets();
        } else {
            screen.setFitsSystemWindows(true);
        }
    }

    private void applyScreenSize() {
        layoutMode = currentLayoutMode(getResources().getConfiguration());
        coverMode = CoverScreenPolicy.cover(layoutMode);
        landscapeLayout = layoutMode == CoverScreenPolicy.Mode.WIDE;
        compactLayout = layoutMode == CoverScreenPolicy.Mode.COMPACT || coverMode;
        typography.useCover(coverMode);
        typography.defaults(screen);
        applyDeviceBandMode();
        if (landscapeLayout) {
            detach(heatMeter);
            heatMeter.setPadding(dp(8), 0, dp(8), 0);
            header.addView(heatMeter, header.indexOfChild(info), new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT));
            arrangeLandscapeTopRow();
            applyComposerRowHeight(false);
            lastCollapseFraction = -1f;
            setHeaderCollapse(0);
        }
        if (compactLayout) {
            LinearLayout root = (LinearLayout) screen;
            ((ViewGroup) status.getParent()).removeView(status);
            status.setPadding(dp(12), dp(2), dp(12), dp(2));
            status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            status.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
            status.setSingleLine(false);
            status.setMaxLines(2);
            status.setEllipsize(TextUtils.TruncateAt.END);
            status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
            int afterHeader = root.indexOfChild(header) + 1;
            root.addView(status, afterHeader, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            if (!coverMode) {
                compactLaneStatus = newspaperText("", 13, false, false);
                typography.tabular(compactLaneStatus);
                compactLaneStatus.setPadding(dp(12), 0, dp(12), dp(2));
                compactLaneStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
                root.addView(compactLaneStatus, afterHeader + 1,
                        new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                                LinearLayout.LayoutParams.WRAP_CONTENT));
            }
            updateCompactLaneStatus();
            resultsScroll.addOnLayoutChangeListener((view, left, top, right, bottom,
                    oldLeft, oldTop, oldRight, oldBottom) -> {
                if (compactImeVisible && bottom - top != oldBottom - oldTop) {
                    view.removeCallbacks(coverResultsCheck);
                    view.post(coverResultsCheck);
                }
            });
        }
        if (NewspaperLayoutDecision.stackedHeader(
                getResources().getConfiguration().fontScale, compactLayout, landscapeLayout)) {
            stackLargeFontHeader();
        }
        applyQuestionLayout(question);
        applyResultsContentPadding();
        syncErrorVisibility();
        if (coverMode) applyCoverChrome();
        arrangeArticles();
        setupNotesDock();
    }

    /** On a short inner screen, the input and device band share a row above the answer columns. */
    private void arrangeLandscapeTopRow() {
        LinearLayout root = (LinearLayout) screen;
        LinearLayout composer = findViewById(R.id.composer);
        int index = root.indexOfChild(composer);
        if (index < 0 || deviceBand == null) return;
        root.removeView(composer);
        detach(deviceBand);
        LinearLayout topRow = new LinearLayout(this);
        topRow.setOrientation(LinearLayout.HORIZONTAL);
        topRow.setGravity(Gravity.CENTER_VERTICAL);
        topRow.setPadding(dp(12), 0, dp(12), 0);
        topRow.addView(composer, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        LinearLayout.LayoutParams bandParams = new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1.6f);
        bandParams.leftMargin = dp(8);
        topRow.addView(deviceBand, bandParams);
        root.addView(topRow, index, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
    }

    private CoverScreenPolicy.Mode currentLayoutMode(Configuration config) {
        int displayId = 0;
        try {
            android.view.Display display = Build.VERSION.SDK_INT >= 30 ? getDisplay()
                    : getWindowManager().getDefaultDisplay();
            if (display != null) displayId = display.getDisplayId();
        } catch (RuntimeException ignored) {
            // Fall back to size alone.
        }
        return CoverScreenPolicy.select(config.screenWidthDp, config.screenHeightDp, displayId);
    }

    /**
     * The manifest declares configChanges for screen size, so folding does not restart the activity.
     * Only rebuild when the layout family changes (inner page, compact page, cover page).
     */
    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        if (recreating) return;
        if (CoverScreenPolicy.needsRecreate(layoutMode, currentLayoutMode(newConfig))) {
            foldSnapshot = pairingPending ? null : snapshot;
            recreating = true;
            recreate();
        } else {
            // Same layout family but a new window size (split-screen, pop-up, Flex Window resize).
            arrangeArticles();
            applyUi();
        }
    }

    /** Cover-only chrome: smaller masthead, no dateline, shorter composer. */
    private void applyCoverChrome() {
        typography.display(bigMasthead, CoverScreenPolicy.MASTHEAD_SP);
        if (mastheadBlock.getChildCount() > 1) mastheadBlock.getChildAt(1).setVisibility(View.GONE);
        applyComposerRowHeight(false);
    }

    private void applyComposerRowHeight(boolean keyboardVisible) {
        int rowHeight = dp(coverMode ? CoverScreenPolicy.composerRowDp(keyboardVisible)
                : CoverLayoutPolicy.composerRowHeightDp(
                        compactLayout, keyboardVisible, landscapeLayout));
        LinearLayout composer = findViewById(R.id.composer);
        LinearLayout row = findViewById(R.id.input_row);
        if (composer != null) {
            composer.setBackgroundColor(themeColor(R.color.newspaper_paper));
            composer.setClipChildren(false);
            composer.setClipToPadding(false);
            int vertical = dp(coverMode ? 6 : 8);
            composer.setPadding(dp(12), vertical, dp(12), vertical);
        }
        if (row != null) {
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setClipChildren(false);
            row.setClipToPadding(false);
            row.setPadding(dp(1), dp(1), dp(1), dp(1));
            row.setBackgroundColor(themeColor(R.color.newspaper_paper));
        }
        LinearLayout.LayoutParams promptParams = prompt.getLayoutParams() instanceof LinearLayout.LayoutParams
                ? (LinearLayout.LayoutParams) prompt.getLayoutParams()
                : new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        promptParams.width = 0;
        promptParams.height = rowHeight;
        promptParams.weight = 1;
        promptParams.topMargin = 0;
        promptParams.bottomMargin = 0;
        promptParams.leftMargin = 0;
        promptParams.rightMargin = 0;
        prompt.setMinHeight(rowHeight);
        prompt.setPadding(dp(12), dp(10), dp(12), dp(10));
        prompt.setIncludeFontPadding(true);
        prompt.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        prompt.setBackground(panelDrawable(palette.stroke()));
        prompt.setHintTextColor(themeColor(R.color.you_asked_label));
        prompt.setTextColor(themeColor(R.color.newspaper_ink));
        prompt.setLayoutParams(promptParams);
        for (Button button : new Button[]{send, stop, reconnect}) {
            LinearLayout.LayoutParams action = button.getLayoutParams() instanceof LinearLayout.LayoutParams
                    ? (LinearLayout.LayoutParams) button.getLayoutParams()
                    : new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, rowHeight);
            action.width = LinearLayout.LayoutParams.WRAP_CONTENT;
            action.height = rowHeight;
            action.leftMargin = dp(6);
            action.topMargin = 0;
            action.bottomMargin = 0;
            action.gravity = Gravity.CENTER_VERTICAL;
            button.setMinHeight(rowHeight);
            button.setMinimumHeight(rowHeight);
            button.setMinWidth(dp(84));
            button.setMinimumWidth(dp(84));
            button.setPaddingRelative(dp(8), 0, dp(8), 0);
            zeroButtonInsets(button);
            button.setIncludeFontPadding(false);
            button.setGravity(Gravity.CENTER);
            button.setLayoutParams(action);
        }
    }

    /** Framework Button insets default to a few dp and sit the label high; zero them on API 29+. */
    private static void zeroButtonInsets(Button button) {
        try {
            button.getClass().getMethod("setInsetTop", int.class).invoke(button, 0);
            button.getClass().getMethod("setInsetBottom", int.class).invoke(button, 0);
        } catch (ReflectiveOperationException ignored) {
            // Older stubs have no inset setters; padding already has no vertical inset.
        }
    }

    private Map<String, String> coverStates() {
        Map<String, String> states = new HashMap<>();
        for (String pane : paneOrder) {
            PaneViews article = paneViews.get(pane);
            if (article != null) states.put(pane,
                    CoverScreenPolicy.visibleState(article.state.getText().toString()));
        }
        return states;
    }

    private boolean coverUserBusy() {
        if (articleDialog != null && articleDialog.isShowing()) return true;
        if (summaryDialog != null && summaryDialog.isShowing()) return true;
        boolean touching = false;
        for (PaneViews article : paneViews.values()) touching |= article.touching;
        long now = SystemClock.uptimeMillis();
        if (touching) coverInteractionMs = now;
        return CoverScreenPolicy.userBusy(touching, false, now, coverInteractionMs);
    }

    /** Re-ranks the visible panes (never under a reader's finger) and refreshes LIVE/PAUSED chips. */
    private void refreshCover() {
        if (!coverMode || paneOrder.isEmpty() || answers == null) return;
        Map<String, String> states = coverStates();
        List<String> wanted = CoverScreenPolicy.visiblePanes(
                paneOrder, states, coverShown, CoverScreenPolicy.MAX_PANES);
        if (CoverScreenPolicy.shouldRearrange(coverShown, wanted, coverUserBusy())) {
            arrangeArticles();
        }
        for (String pane : paneOrder) {
            PaneViews article = paneViews.get(pane);
            if (article == null) continue;
            String state = states.get(pane);
            setIfChanged(article.kicker, CoverScreenPolicy.kicker(pane, state));
            applyTone(article.kicker);
            article.kicker.setBackgroundColor(Color.TRANSPARENT);
            article.kicker.setPadding(dp(6), dp(2), dp(6), dp(2));
        }
        updateCoverMore();
    }

    private void updateCoverMore() {
        if (coverMore == null) return;
        String label = CoverScreenPolicy.moreLabel(
                CoverScreenPolicy.hiddenCount(paneOrder.size(), coverShown.size()));
        setIfChanged(coverMore, label);
        coverMore.setVisibility(label.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void arrangeCoverArticles() {
        // Design lab on the cover: the link schematic only, above the lanes (off by default).
        addLabView();
        coverShown = CoverScreenPolicy.visiblePanes(
                paneOrder, coverStates(), coverShown, CoverScreenPolicy.MAX_PANES);
        for (int i = 0; i < coverShown.size(); i++) {
            PaneViews pane = paneViews.get(coverShown.get(i));
            if (pane == null) continue;
            typography.body(pane.answer, LaneCardLayout.bodySp(true, true));
            putWrapCard(answers, pane.card, LaneCardLayout.MIN_LANE_DP,
                    LaneCardLayout.gapDp(i));
        }
        if (coverMore == null) {
            coverMore = newspaperText("", 13, false, false);
            typography.byline(coverMore);
            coverMore.setPadding(dp(4), dp(8), dp(4), dp(4));
        }
        detach(coverMore);
        answers.addView(coverMore, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        updateCoverMore();
        pinSummaryBar();
    }

    private void setCompactKeyboardMode(boolean keyboardVisible) {
        if (compactImeVisible == keyboardVisible) return;
        compactImeVisible = keyboardVisible;
        prompt.setMaxLines(keyboardVisible ? 1 : 3);
        if (!keyboardVisible) header.setVisibility(View.VISIBLE);
        int mastheadDp = coverMode ? CoverScreenPolicy.mastheadDp(keyboardVisible)
                : CoverLayoutPolicy.mastheadHeightDp(compactLayout, keyboardVisible);
        mastheadBlock.setVisibility(mastheadDp == 0 ? View.GONE : View.VISIBLE);
        applyComposerRowHeight(keyboardVisible);
        ((LinearLayout) findViewById(R.id.composer)).setPadding(dp(12),
                keyboardVisible ? 0 : dp(coverMode ? 2 : 4), dp(12),
                keyboardVisible ? 0 : dp(coverMode ? 4 : 6));
        lastCollapseFraction = -1f;
        setHeaderCollapse(resultsScroll.getScrollY());
        applyComposerState();
        if (keyboardVisible) screen.post(coverResultsCheck);
    }

    private void ensureCoverResultsArea() {
        if (!compactLayout || !compactImeVisible) return;
        int resultsDp = (int) (resultsScroll.getHeight()
                / getResources().getDisplayMetrics().density);
        int target = CoverLayoutPolicy.showTitleRow(resultsDp,
                header.getVisibility() == View.VISIBLE) ? View.VISIBLE : View.GONE;
        if (header.getVisibility() != target) {
            header.setVisibility(target);
            return;
        }
        if (resultsScroll.getHeight() > 0) revealVisible(false);
    }

    private void applyComposerState() {
        findViewById(R.id.composer).setVisibility(View.VISIBLE);
        prompt.setVisibility(View.VISIBLE);
        findViewById(R.id.question_label).setVisibility(View.GONE);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void enableSmoothGrowth(ViewGroup group) {
        if (group == null) return;
        if (reduceMotionEnabled) {
            group.setLayoutTransition(null);
            return;
        }
        LayoutTransition transition = new LayoutTransition();
        transition.enableTransitionType(LayoutTransition.CHANGING);
        transition.setAnimateParentHierarchy(false);
        transition.setDuration(LayoutTransition.CHANGING, LaneCardLayout.GROW_MS);
        group.setLayoutTransition(transition);
    }

    private static final class PaneViews {
        final String pane;
        final LinearLayout card;
        final TextView kicker, heading, byline, state, speed, answer;
        final ScrollView bodyScroll;
        final NewspaperLayoutDecision.FollowTail follow =
                new NewspaperLayoutDecision.FollowTail();
        String renderedAnswerId = "";
        String rawAnswer = "";
        int words;
        float downX, downY;
        boolean touching;
        float lastTouchY;
        boolean userScrolled, programmaticScroll;
        String lastRenderedState = "";
        /** Live line replacing the plain state while the lane streams or thinks. */
        TextView working;
        TextView workingCount;
        LinearLayout workingRow;
        final WorkingSpans workingSpans = new WorkingSpans();

        PaneViews(String pane, LinearLayout card, TextView kicker, TextView heading,
                  TextView byline,
                  TextView state, TextView speed, TextView answer, ScrollView bodyScroll) {
            this.pane = pane;
            this.card = card;
            this.kicker = kicker;
            this.heading = heading;
            this.byline = byline;
            this.state = state;
            this.speed = speed;
            this.answer = answer;
            this.bodyScroll = bodyScroll;
        }
    }

    private TextView newspaperText(String text, int sizeSp, boolean bold, boolean serif) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(themeColor(R.color.newspaper_ink));
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp);
        if (serif && bold) typography.headline(view, sizeSp);
        else if (serif) view.setTypeface(typography.face(TypeConfig.body().face));
        else view.setTypeface(bold ? typography.interSemibold : typography.interMedium);
        return view;
    }

    private AlertDialog showAlert(AlertDialog.Builder builder) {
        AlertDialog dialog = builder.create();
        dialog.show();
        typography.defaults(dialog.getWindow().getDecorView());
        applyPaletteToAlert(dialog);
        return dialog;
    }

    private void applyPaletteToAlert(Dialog dialog) {
        Window window = dialog.getWindow();
        if (window == null) return;
        window.setBackgroundDrawable(new ColorDrawable(themeColor(R.color.newspaper_paper)));
        recolorAlertText(window.getDecorView(), themeColor(R.color.newspaper_ink));
    }

    private void recolorAlertText(View view, int ink) {
        if (view instanceof TextView) ((TextView) view).setTextColor(ink);
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                recolorAlertText(group.getChildAt(i), ink);
            }
        }
    }

    private LinearLayout box() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(LaneCardLayout.CARD_PADDING_DP);
        card.setPadding(pad, pad, pad, pad);
        card.setBackground(panelDrawable(palette.stroke()));
        enableSmoothGrowth(card);
        addReveal(card);
        return card;
    }

    private void addReveal(View view) {
        revealStates.put(view, new NewspaperLayoutDecision.RevealOnce());
        view.setAlpha(0f);
    }

    private void setupNewspaper() {
        typography.defaults(screen);
        header = findViewById(R.id.header);
        answers = findViewById(R.id.answers);
        answers.setOrientation(LinearLayout.VERTICAL);
        TextView title = findViewById(R.id.title);
        smallMasthead = title;
        title.setText(getString(R.string.app_name) + " ⌄");
        title.setContentDescription(getString(R.string.app_name) + ", menu");
        title.setFocusable(true);
        title.setOnClickListener(view -> toggleMenu());
        title.setAccessibilityDelegate(mastheadButtonRole());
        typography.display(title, 20);
        title.setSingleLine(true);
        title.setEllipsize(TextUtils.TruncateAt.END);
        title.setMinHeight(dp(48));
        title.setAlpha(0f);
        title.setLayoutParams(new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1.6f));
        ((ViewGroup) status.getParent()).removeView(status);
        status.setPadding(dp(4), 0, dp(4), 0);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        status.setTypeface(typography.interMedium);
        status.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        status.setSingleLine(true);
        status.setEllipsize(TextUtils.TruncateAt.END);
        header.addView(status, 1, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        heatMeter = newspaperText("", 13, false, false);
        heatMeter.setSingleLine(true);
        heatMeter.setEllipsize(TextUtils.TruncateAt.END);
        heatMeter.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        heatMeter.setPadding(dp(12), 0, dp(12), dp(4));
        heatMeter.setVisibility(View.GONE);
        setupLinkBanner();
        // Keep the heat reading on its own line: it must never steal the title's width.
        LinearLayout root = (LinearLayout) screen;
        root.addView(heatMeter, root.indexOfChild(header) + 1,
                new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));
        batteryNotice = newspaperText("", TypeConfig.body().sizeSp, false, true);
        batteryNotice.setPadding(dp(12), 0, dp(12), dp(4));
        batteryNotice.setVisibility(View.GONE);
        batteryNotice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        root.addView(batteryNotice, root.indexOfChild(heatMeter) + 1,
                new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));
        info.setLayoutParams(new LinearLayout.LayoutParams(dp(52), dp(48)));
        header.setPadding(dp(12), dp(2), dp(12), dp(4));
        bigMasthead = newspaperText(getString(R.string.app_name) + " ⌄", 34, true, true);
        typography.display(bigMasthead, 34);
        bigMasthead.setContentDescription(getString(R.string.app_name) + ", menu");
        bigMasthead.setFocusable(true);
        bigMasthead.setOnClickListener(view -> toggleMenu());
        bigMasthead.setAccessibilityDelegate(mastheadButtonRole());
        bigMasthead.setGravity(Gravity.CENTER_VERTICAL);
        bigMasthead.setMinHeight(dp(48));
        mastheadBlock = new LinearLayout(this);
        mastheadBlock.setOrientation(LinearLayout.VERTICAL);
        mastheadBlock.setPadding(dp(12), 0, dp(12), 0);
        mastheadBlock.addView(bigMasthead);
        TextView dateline = newspaperText(Dateline.format(LocalDate.now()), 12, false, false);
        pcLabelled(dateline, Dateline.format(LocalDate.now(), ComputerWords.PC));
        dateline.setLetterSpacing(0.08f);
        mastheadBlock.addView(dateline);
        View mastheadRule = new View(this);
        mastheadRule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
        LinearLayout.LayoutParams mastheadRuleParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1));
        mastheadRuleParams.topMargin = dp(6);
        mastheadRuleParams.bottomMargin = dp(6);
        mastheadBlock.addView(mastheadRule, mastheadRuleParams);
        mastheadBlock.addOnLayoutChangeListener((view, left, top, right, bottom,
                oldLeft, oldTop, oldRight, oldBottom) -> {
            if (lastCollapseFraction == 0f && bottom > top) {
                expandedMastheadHeightPx = Math.max(expandedMastheadHeightPx, bottom - top);
            }
        });
        ((LinearLayout) screen).addView(mastheadBlock, 0,
                new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));

        findViewById(R.id.question_label).setVisibility(View.GONE);
        typography.state(phoneState);
        typography.state(gpuState);
        applyPairingTypography();
        prompt.setMinLines(1);
        prompt.setMaxLines(3);
        applyComposerRowHeight(false);
        resultsScroll.setOnScrollChangeListener((view, x, y, oldX, oldY) -> {
            coverInteractionMs = SystemClock.uptimeMillis();
            setHeaderCollapse(y);
            revealVisible(false);
            syncWorkingAnimation();
        });
        LinearLayout content = findViewById(R.id.content);
        setupDeviceBand();
        content.removeView(deviceBand);
        content.addView(deviceBand, 0);
        content.removeView(question);
        content.addView(question, 1);

        LinearLayout phoneCard = findViewById(R.id.phone_card);
        LinearLayout gpuCard = findViewById(R.id.gpu_card);
        TextView phoneHeading = (TextView) phoneCard.getChildAt(0);
        answers.removeView(phoneCard);
        answers.removeView(gpuCard);
        paneViews.put("gpu", prepareArticle("gpu", gpuCard, gpuHeading, gpuState, gpuAnswer));
        paneViews.put("phone", prepareArticle("phone", phoneCard, phoneHeading,
                phoneState, phoneAnswer));
        paneOrder.add("gpu");
        paneOrder.add("phone");
        columns = new LinearLayout(this);
        columns.setOrientation(LinearLayout.HORIZONTAL);
        leftColumn = new LinearLayout(this);
        leftColumn.setOrientation(LinearLayout.VERTICAL);
        rightColumn = new LinearLayout(this);
        rightColumn.setOrientation(LinearLayout.VERTICAL);
        timingCard = box();
        TextView tonightKicker = newspaperText(getString(R.string.tonight_label), 12, true, false);
        typography.kicker(tonightKicker);
        timingCard.addView(tonightKicker);
        tonightCount = newspaperText(getString(R.string.tonight_initial_time), 28, true, false);
        typography.tabular(tonightCount);
        timingCard.addView(tonightCount);
        tonightProvenance = newspaperText("", 13, false, false);
        typography.tabular(tonightProvenance);
        timingCard.addView(tonightProvenance);
        // tonightTiming keeps the plain text for History; tonightRows is what the card shows.
        tonightTiming = newspaperText("", LaneCardLayout.LABEL_SP, false, false);
        tonightTiming.setVisibility(View.GONE);
        timingCard.addView(tonightTiming);
        tonightRows = new LinearLayout(this);
        tonightRows.setOrientation(LinearLayout.VERTICAL);
        tonightRows.setPadding(0, dp(6), 0, 0);
        timingCard.addView(tonightRows, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        tonightLeader = newspaperText("", 21, true, false);
        typography.tabular(tonightLeader);
        tonightLeader.setPadding(0, dp(6), 0, 0);
        tonightLeader.setVisibility(View.GONE);
        timingCard.addView(tonightLeader);
        setTonightTiming(pcWords(R.string.tonight_waiting));
        notesCard = box();
        notes = new LinedNotesEditText(this);
        notes.setTextColor(themeColor(R.color.newspaper_ink));
        notes.setHintTextColor(themeColor(R.color.you_asked_label));
        notes.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        notes.setLineSpacing(0f, 1.6f);
        notes.setTypeface(typography.smTextRegular);
        notes.setHint(NotesCompact.EMPTY_HINT);
        notes.setGravity(Gravity.TOP | Gravity.START);
        notes.setBackgroundColor(themeColor(R.color.newspaper_paper));
        notes.setText(getPreferences(MODE_PRIVATE).getString("local_newspaper_notes", ""));
        notes.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence value, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence value, int start, int before, int count) {
                getPreferences(MODE_PRIVATE).edit()
                        .putString("local_newspaper_notes", value.toString()).apply();
            }
            @Override public void afterTextChanged(Editable value) { applyNotesCompact(); }
        });
        LinearLayout.LayoutParams notesParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        notesCard.addView(notes, notesParams);
        notesCard.setOnDragListener(notesTargetListener());
        applyNotesCompact();
        summaryCard = box();
        summaryHeading = newspaperText(getString(R.string.summary_label), typography.headingSp(), true, true);
        summaryCard.addView(summaryHeading);
        summaryText = newspaperText(getString(R.string.summary_empty),
                typography.bodySp(), false, true);
        typography.body(summaryText, typography.bodySp());
        summaryCard.addView(summaryText, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        resultsScroll.post(() -> {
            revealVisible(true);
            initialRevealDone = true;
        });
    }

    /** Give the title, live state, and controls their own width on the inner screen. */
    private void stackLargeFontHeader() {
        header.setOrientation(LinearLayout.VERTICAL);
        smallMasthead.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        smallMasthead.setSingleLine(false);
        smallMasthead.setMaxLines(Integer.MAX_VALUE);
        smallMasthead.setEllipsize(null);
        status.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        status.setPadding(0, dp(2), 0, dp(2));
        status.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        status.setSingleLine(false);
        status.setMaxLines(Integer.MAX_VALUE);
        status.setEllipsize(null);

        header.removeView(info);
        header.removeView(settings);
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams actionsParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        actionsParams.topMargin = dp(8);
        header.addView(actions, actionsParams);
        info.setMinHeight(dp(48));
        settings.setMinHeight(dp(48));
        info.setSingleLine(false);
        settings.setSingleLine(false);
        info.setMaxLines(Integer.MAX_VALUE);
        settings.setMaxLines(Integer.MAX_VALUE);
        info.setEllipsize(null);
        settings.setEllipsize(null);
        actions.addView(info, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        LinearLayout.LayoutParams settingsParams = new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        settingsParams.leftMargin = dp(12);
        actions.addView(settings, settingsParams);
    }

    private void toggleMenu() {
        if (menuPopup != null && menuPopup.isShowing()) {
            menuPopup.dismiss();
            return;
        }
        menuState.toggle();
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(dp(1), dp(1), dp(1), dp(1));
        list.setBackgroundResource(R.drawable.newspaper_panel);
        for (int i = 0; i < MenuState.ENTRIES.size(); i++) {
            final int index = i;
            TextView item = newspaperText(MenuState.ENTRIES.get(i), 18, false, true);
            item.setGravity(Gravity.CENTER_VERTICAL);
            item.setPadding(dp(16), 0, dp(16), 0);
            item.setBackgroundColor(themeColor(R.color.newspaper_paper));
            item.setFocusable(true);
            item.setOnClickListener(view -> {
                String choice = menuState.select(index);
                if (menuPopup != null) menuPopup.dismiss();
                if (choice == null) return;
                switch (choice) {
                    case "Model Selection": showModelSelection(); break;
                    case "History": showHistory(); break;
                    case "Settings": showSettings(); break;
                    case "Quit": confirmQuit(); break;
                    default: throw new AssertionError(choice);
                }
            });
            list.addView(item, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(52)));
            if (i < MenuState.ENTRIES.size() - 1) {
                View rule = new View(this);
                rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
                list.addView(rule, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
            }
        }
        PopupWindow popup = new PopupWindow(list, dp(230),
                dp(52) * MenuState.ENTRIES.size() + dp(MenuState.ENTRIES.size() + 1), true);
        menuPopup = popup;
        popup.setBackgroundDrawable(new ColorDrawable(themeColor(R.color.newspaper_paper)));
        popup.setOutsideTouchable(true);
        popup.setElevation(0);
        popup.setAnimationStyle(0); // Plain show/hide also respects zero animator scale.
        popup.setOnDismissListener(() -> {
            menuState.dismiss();
            if (menuPopup == popup) menuPopup = null;
        });
        popup.showAsDropDown(header, dp(12), 0);
    }

    private View.AccessibilityDelegate mastheadButtonRole() {
        return new View.AccessibilityDelegate() {
            @Override public void onInitializeAccessibilityNodeInfo(View host,
                    AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(Button.class.getName());
                info.setClickable(true);
            }
        };
    }

    private PaneViews prepareArticle(String pane, LinearLayout card, TextView heading,
                                     TextView stateView, TextView answerView) {
        int pad = dp(LaneCardLayout.CARD_PADDING_DP);
        card.setPadding(pad, pad, pad, pad);
        card.setBackground(panelDrawable(palette.stroke()));
        typography.headline(heading, typography.headingSp());
        typography.state(stateView);
        typography.tabular(stateView);
        stateView.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        TextView kicker = newspaperText(PaneKeys.kicker(pane), typography.labelSp(), true, false);
        if (PaneKeys.pc(pane)) pcLabelled(kicker, PaneKeys.kicker(pane, ComputerWords.PC));
        typography.kicker(kicker);
        card.addView(kicker, 0);
        TextView byline = newspaperText("", typography.labelSp(), false, false);
        typography.byline(byline);
        byline.setIncludeFontPadding(true);
        byline.setPadding(0, dp(2), 0, dp(2));
        byline.setTextColor(themeColor(R.color.newspaper_ink));
        card.addView(byline, 2);
        TextView speed = newspaperText("", typography.labelSp(), false, false);
        typography.state(speed);
        speed.setVisibility(View.GONE);
        card.addView(speed, 4);
        card.removeView(answerView);
        typography.body(answerView, typography.bodySp());
        LinearLayout.LayoutParams bodyParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        bodyParams.topMargin = dp(6);
        card.addView(answerView, bodyParams);
        // No inner ScrollView: the card grows with the answer; the page scrolls.
        PaneViews paneView = new PaneViews(pane, card, kicker, heading, byline,
                stateView, speed, answerView, null);
        paneView.working = workingLine(stateView);
        paneView.workingCount = workingCountLine();
        paneView.workingRow = new LinearLayout(this);
        paneView.workingRow.setOrientation(LinearLayout.HORIZONTAL);
        paneView.workingRow.setGravity(Gravity.CENTER_VERTICAL);
        paneView.workingRow.setVisibility(View.GONE);
        paneView.workingRow.addView(paneView.working,
                new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));
        paneView.workingRow.addView(paneView.workingCount,
                new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        int stateIndex = card.indexOfChild(stateView);
        ViewGroup.MarginLayoutParams stateMargins =
                (ViewGroup.MarginLayoutParams) stateView.getLayoutParams();
        LinearLayout.LayoutParams workingMargins = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        workingMargins.setMargins(stateMargins.leftMargin, stateMargins.topMargin,
                stateMargins.rightMargin, stateMargins.bottomMargin);
        card.addView(paneView.workingRow, stateIndex >= 0 ? stateIndex + 1 : card.getChildCount(),
                workingMargins);
        card.addOnLayoutChangeListener((view, left, top, right, bottom,
                oldLeft, oldTop, oldRight, oldBottom) -> syncWorkingAnimation());
        View.OnClickListener open = view -> {
            if (pane.equals(suppressArticleClick)) {
                suppressArticleClick = null;
                return;
            }
            expandArticle(pane);
        };
        // The heading is the one TalkBack action. Touch can open the card elsewhere too.
        card.setOnClickListener(open);
        card.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        heading.setMinHeight(dp(48));
        heading.setGravity(Gravity.CENTER_VERTICAL);
        heading.setFocusable(true);
        heading.setOnClickListener(open);
        answerView.setOnClickListener(open);
        enableSmoothGrowth(card);
        addReveal(card);
        addLaneRetryButton(pane, card);
        wireNotesDrag(paneView);
        return paneView;
    }

    private void watchArticleLabels(LinearLayout card, ScrollView body, TextView answer) {
        View.OnLayoutChangeListener check = (view, left, top, right, bottom,
                oldLeft, oldTop, oldRight, oldBottom) ->
                card.post(() -> ensureArticleMinHeight(card, body, answer));
        card.addOnLayoutChangeListener(check);
        for (int i = 0; i < card.getChildCount(); i++) {
            View child = card.getChildAt(i);
            if (child != body) child.addOnLayoutChangeListener(check);
        }
    }

    private void ensureArticleMinHeight(LinearLayout card, ScrollView body, TextView answer) {
        if (card.getWidth() <= 0 || card.getLayoutParams() == null) return;
        int width = card.getWidth() - card.getPaddingLeft() - card.getPaddingRight();
        int required = card.getPaddingTop() + card.getPaddingBottom()
                + Math.max(1, answer.getLineHeight());
        for (int i = 0; i < card.getChildCount(); i++) {
            View child = card.getChildAt(i);
            if (child.getVisibility() == View.GONE) continue;
            ViewGroup.MarginLayoutParams margins =
                    (ViewGroup.MarginLayoutParams) child.getLayoutParams();
            required += margins.topMargin + margins.bottomMargin;
            if (child == body) continue;
            int childWidth = Math.max(0, width - margins.leftMargin - margins.rightMargin);
            child.measure(View.MeasureSpec.makeMeasureSpec(childWidth,
                            View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
            required += child.getMeasuredHeight();
        }
        ViewGroup.LayoutParams params = card.getLayoutParams();
        if (params.height > 0 && params.height < required) {
            params.height = required;
            card.setLayoutParams(params);
        }
    }

    private PaneViews createExtraArticle(String pane) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        TextView heading = newspaperText(PaneKeys.fallbackLabel(pane), 19, true, true);
        TextView stateView = newspaperText(getString(R.string.checking), 13, true, false);
        TextView answerView = newspaperText("", 17, false, true);
        answerView.setTextIsSelectable(true);
        card.addView(heading);
        card.addView(stateView);
        card.addView(answerView);
        return prepareArticle(pane, card, heading, stateView, answerView);
    }

    private void updateBodyViewport(ScrollView scroll, TextView answer) {
        if (scroll.getHeight() <= 0) return;
        int available = scroll.getHeight() - scroll.getPaddingTop();
        int viewport = LineSnap.viewportFor(available, Math.max(1, answer.getLineHeight()));
        int bottom = available - viewport;
        if (scroll.getPaddingBottom() != bottom) {
            scroll.setPadding(scroll.getPaddingLeft(), scroll.getPaddingTop(),
                    scroll.getPaddingRight(), bottom);
        }
    }

    private static int[] lineTops(TextView answer) {
        Layout layout = answer.getLayout();
        if (layout == null || layout.getLineCount() == 0) return new int[]{0};
        int[] tops = new int[layout.getLineCount()];
        for (int i = 0; i < tops.length; i++) tops[i] = layout.getLineTop(i);
        return tops;
    }

    private static int snappedScrollY(ScrollView scroll, TextView answer, int wanted) {
        int max = ScrollPolicy.maxScroll(answer.getHeight(), scroll.getHeight(),
                scroll.getPaddingTop(), scroll.getPaddingBottom());
        return ScrollPolicy.targetScroll(wanted, max, lineTops(answer));
    }

    private void alignArticleScroll(PaneViews article, boolean textChanged,
                                    boolean reachedDone, boolean reachedPaused) {
        if (article.bodyScroll == null) return;
        if (!ScrollPolicy.shouldAlign(textChanged, reachedDone, reachedPaused,
                article.touching)) return;
        String id = article.renderedAnswerId;
        article.bodyScroll.post(() -> {
            if (!id.equals(article.renderedAnswerId)) return;
            int wanted;
            if ("done".equals(article.lastRenderedState)) {
                wanted = article.userScrolled ? article.bodyScroll.getScrollY() : 0;
            } else if ("paused".equals(article.lastRenderedState)) {
                wanted = article.bodyScroll.getScrollY();
            } else if (textChanged && article.follow.following()) {
                wanted = Integer.MAX_VALUE;
            } else return;
            article.programmaticScroll = true;
            article.bodyScroll.scrollTo(0, snappedScrollY(
                    article.bodyScroll, article.answer, wanted));
            article.programmaticScroll = false;
        });
    }

    private static void detach(View view) {
        if (view.getParent() instanceof ViewGroup) ((ViewGroup) view.getParent()).removeView(view);
    }

    /** The NOTES card shrinks to its content: one short line when empty, no reserved height. */
    private void applyNotesCompact() {
        if (notes == null || notesCard == null) return;
        notes.setMinHeight(dp(NotesCompact.editorMinDp(notes.getText())));
        if (notesDock == null || notesDock.getVisibility() != View.VISIBLE) {
            notesCard.setMinimumHeight(dp(NotesCompact.cardMinDp(notes.getText())));
        } else {
            notesCard.setMinimumHeight(0);
        }
        updateNotesTab();
    }

    private void putWrapCard(LinearLayout parent, View card, int minimumHeightDp,
                             int gapDp) {
        detach(card);
        card.setMinimumHeight(dp(minimumHeightDp));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(gapDp);
        parent.addView(card, params);
    }

    private void arrangeArticles() {
        if (answers == null || timingCard == null || paneOrder.isEmpty()) return;
        answers.removeAllViews();
        leftColumn.removeAllViews();
        rightColumn.removeAllViews();
        columns.removeAllViews();
        int columnCount = DeviceLayoutPolicy.columns(
                getResources().getConfiguration().screenWidthDp, coverMode, paneOrder.size());
        if (coverMode) {
            arrangeCoverArticles();
        } else if (columnCount == 1) {
            addLabView();
            List<String> ordered = orderedDevicePanes();
            for (int i = 0; i < ordered.size(); i++) {
                PaneViews pane = paneViews.get(ordered.get(i));
                typography.body(pane.answer, typography.bodySp());
                putWrapCard(answers, pane.card, LaneCardLayout.MIN_LANE_DP,
                        LaneCardLayout.gapDp(i));
            }
            putWrapCard(answers, timingCard, TIMING_CARD_MIN_DP, LaneCardLayout.CARD_GAP_DP);
            pinSummaryBar();
        } else {
            // Phone answers stay left; computer answers stay right. The primary
            // computer answer leads its column.
            addLabView();
            if (!landscapeLayout) putWrapCard(answers, timingCard, TIMING_CARD_MIN_DP, 0);
            List<String> ordered = orderedDevicePanes();
            for (String pane : paneOrder) {
                typography.body(paneViews.get(pane).answer, typography.bodySp());
            }
            LinearLayout.LayoutParams columnsParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            columnsParams.topMargin = dp(LaneCardLayout.CARD_GAP_DP);
            if (!ordered.isEmpty()) {
                columns.addView(leftColumn, new LinearLayout.LayoutParams(0,
                        LinearLayout.LayoutParams.WRAP_CONTENT, 0.5f));
                LinearLayout.LayoutParams rightParams = new LinearLayout.LayoutParams(0,
                        LinearLayout.LayoutParams.WRAP_CONTENT, 0.5f);
                rightParams.leftMargin = dp(LaneCardLayout.CARD_GAP_DP);
                columns.addView(rightColumn, rightParams);
                answers.addView(columns, columnsParams);
                for (String pane : ordered) {
                    JSONObject lane = paneOf(snapshot, pane);
                    DeviceLayoutPolicy.Side side = DeviceLayoutPolicy.side(pane,
                            lane == null ? "" : lane.optString("kind"));
                    DeviceLayoutPolicy.Side placed = DeviceLayoutPolicy.column(side,
                            leftColumn.getChildCount(), rightColumn.getChildCount());
                    LinearLayout target = placed == DeviceLayoutPolicy.Side.PHONE
                            ? leftColumn : rightColumn;
                    putWrapCard(target, paneViews.get(pane).card, LaneCardLayout.MIN_LANE_DP,
                            target.getChildCount() == 0 ? 0 : LaneCardLayout.CARD_GAP_DP);
                }
            }
            if (landscapeLayout) {
                putWrapCard(answers, timingCard, TIMING_CARD_MIN_DP, LaneCardLayout.CARD_GAP_DP);
            }
            pinSummaryBar();
        }
        resultsScroll.post(() -> {
            revealVisible(!initialRevealDone);
            syncWorkingAnimation();
        });
    }

    private List<String> orderedDevicePanes() {
        Map<String, String> kinds = new HashMap<>();
        for (String pane : paneOrder) {
            JSONObject lane = paneOf(snapshot, pane);
            kinds.put(pane, lane == null ? "" : lane.optString("kind"));
        }
        return DeviceLayoutPolicy.orderedPanes(paneOrder, kinds);
    }

    private boolean readReducedMotion() {
        float scale = Settings.Global.getFloat(getContentResolver(),
                Settings.Global.ANIMATOR_DURATION_SCALE, 1f);
        boolean remove = Settings.Secure.getInt(getContentResolver(),
                "accessibility_remove_animations", 0) != 0;
        return NewspaperLayoutDecision.reducedMotion(scale, remove);
    }

    private void setHeaderCollapse(int scrollY) {
        float fraction = landscapeLayout || compactImeVisible ? 1f
                : reduceMotionEnabled ? (scrollY > 0 ? 1f : 0f)
                : NewspaperLayoutDecision.collapseFraction(scrollY, dp(88));
        if (fraction == lastCollapseFraction) return;
        lastCollapseFraction = fraction;
        ViewGroup.LayoutParams params = mastheadBlock.getLayoutParams();
        int step = dp(4);
        if (fraction == 0f && mastheadBlock.getHeight() > expandedMastheadHeightPx) {
            expandedMastheadHeightPx = mastheadBlock.getHeight();
        }
        int naturalHeight = expandedMastheadHeightPx > 0
                ? expandedMastheadHeightPx : dp(88);
        int target = fraction == 0f ? ViewGroup.LayoutParams.WRAP_CONTENT
                : Math.max(0, Math.round(naturalHeight * (1f - fraction) / step) * step);
        if (params.height != target) {
            params.height = target;
            mastheadBlock.setLayoutParams(params);
        }
        // Hard hand-off, never a cross-fade: the app name is drawn once, not twice and ghosted.
        float bigAlpha = MastheadPolicy.bigAlpha(fraction);
        float smallAlpha = MastheadPolicy.smallAlpha(fraction);
        mastheadBlock.setAlpha(bigAlpha);
        smallMasthead.setAlpha(smallAlpha);
        // The hidden title must not take width from the status on narrow screens.
        smallMasthead.setVisibility(smallAlpha > 0f ? View.VISIBLE : View.GONE);
        bigMasthead.setEnabled(bigAlpha > 0f);
        smallMasthead.setEnabled(smallAlpha > 0f);
        bigMasthead.setImportantForAccessibility(fraction < 0.5f
                ? View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
                : View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        smallMasthead.setImportantForAccessibility(fraction >= 0.5f
                ? View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
                : View.IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    private void revealVisible(boolean firstLayout) {
        Rect visible = new Rect();
        if (!resultsScroll.getGlobalVisibleRect(visible)) return;
        Boolean skip = null;
        for (Map.Entry<View, NewspaperLayoutDecision.RevealOnce> item : revealStates.entrySet()) {
            View card = item.getKey();
            if (!card.isAttachedToWindow() || item.getValue().revealed()) continue;
            Rect bounds = new Rect();
            if (!card.getGlobalVisibleRect(bounds) || !Rect.intersects(bounds, visible)) continue;
            if (!item.getValue().enter(true)) continue;
            if (skip == null) {
                reduceMotionEnabled = readReducedMotion();
                skip = reduceMotionEnabled;
            }
            if (NewspaperLayoutDecision.animateReveal(firstLayout, skip)) {
                card.setTranslationY(dp(12));
                card.animate().alpha(1f).translationY(0f).setDuration(180).start();
            } else {
                card.setAlpha(1f);
                card.setTranslationY(0f);
            }
        }
    }

    private void expandArticle(String pane) {
        PaneViews article = paneViews.get(pane);
        if (article == null || articleDialog != null && articleDialog.isShowing()) return;
        Dialog dialog = new Dialog(this, R.style.NewspaperDialogTheme) {
            @Override public void onWindowFocusChanged(boolean hasFocus) {
                super.onWindowFocusChanged(hasFocus);
                syncWorkingAnimation();
            }
        };
        articleDialog = dialog;
        expandedPane = pane;
        // The spans belong to the previous dialog's TextView, even when its line is identical.
        expandedWorkingSpans.line = "";
        expandedUserScrolled = false;
        expandedWasDone = false;
        expandedWasPaused = false;
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(16), dp(16), dp(16), dp(12));
        page.setBackgroundColor(themeColor(R.color.newspaper_paper));
        padForSystemBars(page);
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        expandedTitle = newspaperText(article.heading.getText().toString(), 26, true, true);
        bar.addView(expandedTitle, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        Button close = new Button(this);
        close.setText(R.string.close);
        close.setAllCaps(false);
        close.setTypeface(typography.interSemibold);
        close.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        close.setTextColor(themeColor(R.color.newspaper_ink));
        close.setBackgroundResource(R.drawable.newspaper_outline);
        close.setOnClickListener(view -> dialog.dismiss());
        bar.addView(close, new LinearLayout.LayoutParams(dp(72), dp(48)));
        page.addView(bar);
        expandedStatus = newspaperText(status.getText().toString(), 13, true, false);
        expandedStatus.setTypeface(typography.interMedium);
        page.addView(expandedStatus);
        expandedByline = newspaperText(article.byline.getText().toString(), 13, false, false);
        typography.byline(expandedByline);
        page.addView(expandedByline);
        expandedState = newspaperText("", 13, true, false);
        typography.state(expandedState);
        typography.tabular(expandedState);
        expandedState.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        expandedState.setAccessibilityDelegate(new View.AccessibilityDelegate() {
            @Override public void onInitializeAccessibilityNodeInfo(View host,
                    AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                CharSequence state = article.state.getText();
                info.setContentDescription(WorkingIndicator.working(state)
                        ? WorkingIndicator.spoken(state, 0) : state);
            }
        });
        expandedState.addOnLayoutChangeListener((view, left, top, right, bottom,
                oldLeft, oldTop, oldRight, oldBottom) -> syncWorkingAnimation());
        expandedWorkingCount = workingCountLine();
        LinearLayout expandedStateRow = new LinearLayout(this);
        expandedStateRow.setOrientation(LinearLayout.HORIZONTAL);
        expandedStateRow.setGravity(Gravity.CENTER_VERTICAL);
        expandedStateRow.addView(expandedState,
                new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        expandedStateRow.addView(expandedWorkingCount,
                new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));
        page.addView(expandedStateRow);
        expandedScroll = new ScrollView(this);
        expandedFollow = new NewspaperLayoutDecision.FollowTail();
        expandedAnswer = newspaperText("", 20, false, true);
        typography.body(expandedAnswer, 20);
        expandedAnswer.setTextIsSelectable(true);
        expandedScroll.addView(expandedAnswer);
        expandedScroll.setOnScrollChangeListener((view, x, y, oldX, oldY) -> {
            if (expandedProgrammaticScroll) return;
            if (expandedFollow != null && expandedAnswer != null) {
                if (expandedTouching || expandedUserScrolled) {
                    int max = ScrollPolicy.maxScroll(expandedAnswer.getHeight(),
                            expandedScroll.getHeight(), expandedScroll.getPaddingTop(),
                            expandedScroll.getPaddingBottom());
                    expandedFollow.userMoved(oldY, y, max);
                }
                if (expandedTouching && y != oldY) expandedUserScrolled = true;
            }
        });
        expandedScroll.setOnTouchListener((view, event) -> {
            if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
                expandedTouching = true;
                expandedTouchY = event.getY();
            } else if (event.getActionMasked() == MotionEvent.ACTION_MOVE) {
                if (Math.abs(event.getY() - expandedTouchY) > dp(2)) {
                    expandedUserScrolled = true;
                }
                if (expandedFollow != null && event.getY() > expandedTouchY + 1) {
                    expandedFollow.userMoved(1, 0, 1);
                }
                expandedTouchY = event.getY();
            } else if (event.getActionMasked() == MotionEvent.ACTION_UP
                    || event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                expandedTouching = false;
            }
            return false;
        });
        LinearLayout.LayoutParams body = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1);
        body.topMargin = dp(14);
        page.addView(expandedScroll, body);
        dialog.setContentView(page);
        dialog.setOnDismissListener(ignored -> {
            if (articleDialog == dialog) {
                articleDialog = null;
                expandedPane = null;
                expandedAnswer = null;
                expandedState = null;
                expandedWorkingCount = null;
                expandedStatus = null;
                expandedTitle = null;
                expandedByline = null;
                expandedScroll = null;
                expandedFollow = null;
                expandedTouching = false;
                expandedUserScrolled = false;
                expandedWasDone = false;
                expandedWasPaused = false;
                expandedWorkingSpans.line = "";
                expandedWorkingAnimated = false;
                syncWorkingAnimation();
            }
        });
        updateExpanded(article);
        reduceMotionEnabled = readReducedMotion();
        Window window = dialog.getWindow();
        if (window != null && reduceMotionEnabled) window.setWindowAnimations(0);
        dialog.show();
        if (window != null) {
            window.setBackgroundDrawableResource(R.color.newspaper_paper);
            window.setLayout(WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT);
        }
        syncWorkingAnimation();
    }

    private void updateExpanded(PaneViews article) {
        if (!article.pane.equals(expandedPane) || expandedAnswer == null) return;
        setIfChanged(expandedTitle, article.heading.getText().toString());
        setIfChanged(expandedByline, article.byline.getText().toString());
        if (WorkingIndicator.working(article.state.getText())) {
            setWorkingText(expandedState, expandedWorkingSpans,
                    WorkingIndicator.line(article.state.getText()));
            setIfChanged(expandedWorkingCount, WorkingIndicator.count(article.words));
        } else {
            expandedWorkingSpans.line = "";
            setIfChanged(expandedWorkingCount, "");
            setIfChanged(expandedState, article.state.getText().toString());
        }
        boolean changed = !article.rawAnswer.equals(expandedAnswer.getTag());
        boolean done = article.lastRenderedState.equals("done");
        boolean paused = article.lastRenderedState.equals("paused");
        boolean reachedDone = done && !expandedWasDone;
        expandedWasDone = done;
        boolean reachedPaused = paused && !expandedWasPaused;
        expandedWasPaused = paused;
        boolean followTail = expandedFollow != null && expandedFollow.following();
        if (changed) setMarkdownAnswer(expandedAnswer, article.rawAnswer);
        ScrollView targetScroll = expandedScroll;
        TextView targetAnswer = expandedAnswer;
        if (ScrollPolicy.shouldAlign(changed, reachedDone, reachedPaused, expandedTouching)) targetScroll.post(() -> {
            if (expandedScroll != targetScroll || expandedAnswer != targetAnswer) return;
            String currentState = article.lastRenderedState;
            int wanted = "done".equals(currentState)
                    ? (expandedUserScrolled ? targetScroll.getScrollY() : 0)
                    : "paused".equals(currentState) ? targetScroll.getScrollY()
                    : followTail && expandedFollow != null && expandedFollow.following()
                    ? Integer.MAX_VALUE : targetScroll.getScrollY();
            expandedProgrammaticScroll = true;
            targetScroll.scrollTo(0, snappedScrollY(targetScroll, targetAnswer, wanted));
            expandedProgrammaticScroll = false;
        });
        syncWorkingAnimation();
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (pendingAsk == null && !askRecovery.unresolved()
                && getPreferences(MODE_PRIVATE).getBoolean(PREF_UNRESOLVED_ASK, false)) {
            askRecovery.restoreUnknownUncertain();
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        visible = true;
        IntentFilter filter = new IntentFilter(LinkWatcherService.ACTION_CABLE_CHANGED);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(cableReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(cableReceiver, filter);
        }
        cableConnected = LinkWatcherService.cableConnected(this);
        Intent battery = Build.VERSION.SDK_INT >= 33
                ? registerReceiver(batteryReceiver,
                        new IntentFilter(Intent.ACTION_BATTERY_CHANGED), Context.RECEIVER_NOT_EXPORTED)
                : registerReceiver(batteryReceiver,
                        new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        showBattery(battery);
        awaitingReplugSnapshot = false;
        LinkWatcherService.start(this);
        if (foldRestored) {
            foldRestored = false;
            renderLinkBanner(false, hasVisiblePcWork());
            setMainStatus(getString(R.string.checking_connection));
            updateButtons();
        } else {
            showWaiting();
        }
        schedule(0);
    }

    static boolean isResumed() {
        return resumed;
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        reduceMotionEnabled = readReducedMotion();
        lastCollapseFraction = -1f;
        if (resultsScroll != null) setHeaderCollapse(resultsScroll.getScrollY());
        getSystemService(NotificationManager.class).cancel(LinkWatcherService.LINK_ID);
        tickLab();
        syncWorkingAnimation();
        startHeatMeter();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        syncWorkingAnimation();
    }

    @Override
    protected void onPause() {
        resumed = false;
        stopHeatMeter();
        handler.removeCallbacks(labTicker);
        stopWorkingAnimation();
        super.onPause();
    }

    @Override
    protected void onStop() {
        stopWorkingAnimation();
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        visible = false;
        unregisterReceiver(cableReceiver);
        unregisterReceiver(batteryReceiver);
        handler.removeCallbacks(poll);
        // Keep measured start/duration so TONIGHT does not fall back to dashes
        // after a flip, cover switch, or brief background. elapsedRealtime
        // survives process death until reboot; it is persisted in saveLatestRequest.
        snapshot = null;
        stopWaitingForId = false;
        reachable = false;
        offline = false;
        awaitingReplugSnapshot = false;
        pausedAfterFreshSnapshot = false;
        lastGoodPcAtMs = 0;
        lastPcLiveAtMs = 0;
        latestQuestion = "";
        latestAskedSeconds = 0;
        setIfChanged(question, "");
        question.setVisibility(View.GONE);
        clearNewspaperContent();
        hidePairingUi();
        applyComposerState();
        updateButtons();
        super.onStop();
    }

    @Override
    protected void onSaveInstanceState(Bundle state) {
        state.putString("prompt", prompt.getText().toString());
        super.onSaveInstanceState(state);
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(poll);
        if (isFinishing()) foldSnapshot = null;
        if (quitting) network.shutdown();
        else network.shutdownNow();
        if (menuPopup != null) menuPopup.dismiss();
        if (quitProgressDialog != null) quitProgressDialog.dismiss();
        if (modelSelectionDialog != null) modelSelectionDialog.dismiss();
        if (historyDialog != null) historyDialog.dismiss();
        if (backIssueDialog != null) backIssueDialog.dismiss();
        if (summaryDialog != null) summaryDialog.dismiss();
        if (infoDialog != null) {
            infoDialog.dismiss();
            infoDialog = null;
        }
        if (articleDialog != null) {
            articleDialog.dismiss();
            articleDialog = null;
        }
        super.onDestroy();
    }

    private void schedule(long delayMs) {
        handler.removeCallbacks(poll);
        if (visible && !acting && !polling && !quitting) handler.postDelayed(poll, delayMs);
    }

    private void refresh() {
        if (!visible || polling || acting || quitting) return;
        polling = true;
        network.execute(() -> {
            try {
                JSONObject fresh = client.getSnapshot();
                handler.post(() -> {
                    polling = false;
                    if (!visible || acting || quitting) return;
                    reachable = true;
                    showSnapshot(fresh);
                    schedule(pollDelay(fresh));
                });
            } catch (IOException | JSONException failure) {
                handler.post(() -> {
                    polling = false;
                    if (!visible || acting || quitting) return;
                    reachable = false;
                    showOffline(failure);
                    schedule(2000);
                });
            }
        });
    }

    private static long pollDelay(JSONObject data) {
        JSONObject gpu = data.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        for (String pane : paneNames(data)) {
            if (progressing(answerOf(data, pane))) return 500;
        }
        if (link != null && link.optJSONObject("pending") != null) return 1000;
        return 2000;
    }

    private static List<String> paneNames(JSONObject data) {
        List<String> modelsInOrder = new ArrayList<>();
        JSONArray models = data == null ? null : data.optJSONArray("models");
        for (int i = 0; models != null && i < models.length(); i++) {
            JSONObject model = models.optJSONObject(i);
            String pane = model == null ? "" : model.optString("pane");
            if (model != null && PaneKeys.modelKindMatches(pane, model.optString("kind"))
                    && !PhoneModelGate.hidden(model.optString("label"), model.optString("model"),
                    model.optString("id"), model.optString("maker"))) {
                modelsInOrder.add(pane);
            }
        }
        return PaneKeys.orderedPanes(modelsInOrder);
    }

    private static JSONObject paneOf(JSONObject data, String pane) {
        if (data == null || !PaneKeys.valid(pane)) return null;
        if (!PaneKeys.extra(pane)) return data.optJSONObject(pane);
        JSONArray models = data.optJSONArray("models");
        for (int i = 0; models != null && i < models.length(); i++) {
            JSONObject model = models.optJSONObject(i);
            if (model != null && pane.equals(model.optString("pane"))
                    && PaneKeys.modelKindMatches(pane, model.optString("kind"))) return model;
        }
        return null;
    }

    private Map<String, Boolean> readyPanes(JSONObject data) {
        Map<String, Boolean> ready = new HashMap<>();
        for (String pane : paneNames(data)) {
            JSONObject view = paneOf(data, pane);
            ready.put(pane, "gpu".equals(pane) ? gpuCanQueue(view)
                    : view != null && view.optBoolean("ready"));
        }
        return ready;
    }

    private static JSONObject answerOf(JSONObject data, String pane) {
        JSONObject view = paneOf(data, pane);
        return view == null ? null : view.optJSONObject("answer");
    }

    private boolean anyBlockingOpen() {
        for (String pane : paneNames(snapshot)) {
            if (blockingOpen(pane, answerOf(snapshot, pane))) return true;
        }
        return false;
    }

    private boolean anyReadyPane() {
        return !laneSelection.eligible(paneNames(snapshot), readyPanes(snapshot)).isEmpty();
    }

    private static boolean progressing(JSONObject answer) {
        if (answer == null) return false;
        String state = answer.optString("state");
        return "queued".equals(state) || "waiting".equals(state)
                || "loading".equals(state) || "answering".equals(state);
    }

    /**
     * When this answer's latest state really happened on the elapsed clock: the service's
     * finish stamp for a final answer the app saw late, otherwise now. Pause timing and the
     * lane duration both use it, so a pause closed late cannot eat the duration.
     */
    private long observedAt(JSONObject answer) {
        long now = SystemClock.elapsedRealtime();
        String state = answer.optString("state");
        Long started = answerStarts.get(answer.optString("id"));
        if (started == null || !("done".equals(state) || "failed".equals(state)
                || "cancelled".equals(state))) return now;
        return AnswerFinish.elapsedAt(now, System.currentTimeMillis(),
                answer.optLong("ended_ms", 0), started);
    }

    private static boolean open(JSONObject answer) {
        return progressing(answer) || (answer != null && "paused".equals(answer.optString("state")));
    }

    private boolean awaitingAnswerId() {
        for (String pane : latestRequestedPanes) {
            if (!latestRequestIds.containsKey(pane) && !missingIdExpired(pane)) return true;
        }
        return false;
    }

    private boolean missingIdExpired(String pane) {
        if (!latestRequestedPanes.contains(pane) || latestRequestIds.containsKey(pane)) {
            return false;
        }
        JSONObject answer = answerOf(snapshot, pane);
        long now = SystemClock.elapsedRealtime();
        if (open(answer) && answer.optString("id").isEmpty()) {
            return !askRecovery.blocksOpen(pane, true, "",
                    answer.optString("question"), answer.optDouble("asked", 0), now);
        }
        long age = now - latestRequestAtElapsedMs;
        return latestRequestAtElapsedMs <= 0 || age < 0
                || age >= AskRecoveryPolicy.ID_WAIT_MS;
    }

    private boolean anyMissingIdExpired() {
        for (String pane : latestRequestedPanes) {
            if (missingIdExpired(pane)) return true;
        }
        return false;
    }

    private boolean blockingOpen(String pane, JSONObject answer) {
        return askRecovery.blocksOpen(pane, open(answer),
                answer == null ? "" : answer.optString("id"),
                answer == null ? "" : answer.optString("question"),
                answer == null ? 0 : answer.optDouble("asked", 0),
                SystemClock.elapsedRealtime());
    }

    private void showWaiting() {
        offline = false;
        setMainStatus(getString(R.string.connecting));
        for (PaneViews pane : paneViews.values()) {
            setLaneState(pane.state, pane.card, getString(R.string.checking));
            setPlainAnswer(pane.answer, getString(R.string.empty_answer));
            setLiveSpeed(pane, "");
        }
        updateCompactLaneStatus();
        hidePairingUi();
        applyComposerState();
        setIfChanged(error, "");
        renderLinkBanner(false, hasVisiblePcWork());
        retry.setVisibility(View.GONE);
        updateButtons();
    }

    private void showOffline(Exception failure) {
        offline = true;
        stopWaitingForId = false;
        boolean pcPaused = Boolean.FALSE.equals(cableConnected) && hasVisiblePcWork();
        setMainStatus(getString(R.string.phone_unreachable));
        updateModelSelectionRows();
        if (infoDialog != null && infoDialog.isShowing()) {
            setIfChanged(infoDialog.findViewById(R.id.info_pc_status),
                    getString(R.string.info_unknown));
            infoDialog.findViewById(R.id.info_forget_pc).setVisibility(View.GONE);
        }
        hidePairingUi();
        applyComposerState();
        if (snapshot == null) {
            for (PaneViews pane : paneViews.values()) {
                setLaneState(pane.state, pane.card, getString(R.string.checking));
                setPlainAnswer(pane.answer, getString(R.string.empty_answer));
                setLiveSpeed(pane, "");
            }
        } else {
            for (PaneViews pane : paneViews.values()) {
                if (pcPaused && PaneKeys.pc(pane.pane)
                        && (open(answerOf(snapshot, pane.pane))
                        || isPausedDateline(pane))) {
                    setWaitingLayout(pane, false);
                    setLaneState(pane.state, pane.card, pcWords(R.string.gpu_paused));
                } else {
                    setLaneState(pane.state, pane.card, getString(R.string.stale_snapshot));
                }
                setLiveSpeed(pane, "");
            }
        }
        updateCompactLaneStatus();
        setIfChanged(error, getString(failure instanceof AiClient.ApiException
                && ((AiClient.ApiException) failure).status == 404
                ? R.string.ai_unavailable : R.string.phone_unreachable_detail));
        renderLinkBanner(false, hasVisiblePcWork());
        applyErrorView();
        updateButtons();
    }

    private void showSnapshot(JSONObject data) {
        offline = false;
        awaitingReplugSnapshot = false;
        if (data.optBoolean("locked")) {
            snapshot = null;
            stopWaitingForId = false;
            updateModelSelectionRows();
            latestQuestion = "";
            lastSubmittedQuestion = "";
            latestAskedSeconds = 0;
            questionStartedAtMs = 0;
            overallElapsedMs = -1;
            clearLatestRequest();
            answerStarts.clear();
            answerDurations.clear();
            answerFinishedAt.clear();
            answerTiming.clear();
            setIfChanged(question, "");
            question.setVisibility(View.GONE);
            clearNewspaperContent();
            hidePairingUi();
            applyComposerState();
            setMainStatus(getString(R.string.phone_locked));
            if (infoDialog != null && infoDialog.isShowing()) {
                setIfChanged(infoDialog.findViewById(R.id.info_pc_status),
                        getString(R.string.info_unknown));
                infoDialog.findViewById(R.id.info_forget_pc).setVisibility(View.GONE);
            }
            for (PaneViews pane : paneViews.values()) {
                setLaneState(pane.state, pane.card, getString(R.string.phone_locked));
                updateExpanded(pane);
            }
            setIfChanged(error, "");
            renderLinkBanner(false, false);
            updateButtons();
            return;
        }
        JSONObject phone = data.optJSONObject("phone");
        JSONObject gpu = data.optJSONObject("gpu");
        if (phone == null || gpu == null) {
            reachable = false;
            snapshot = null;
            stopWaitingForId = false;
            showOffline(new IOException("missing panes"));
            return;
        }
        snapshot = data;
        for (String pane : new String[]{"phone", "gpu", "m1", "m2", "m3", "m4",
                "g1", "g2", "g3"}) {
            JSONObject work = answerOf(data, pane);
            askRecovery.blocksOpen(pane, open(work),
                    work == null ? "" : work.optString("id"),
                    work == null ? "" : work.optString("question"),
                    work == null ? 0 : work.optDouble("asked", 0),
                    SystemClock.elapsedRealtime());
        }
        reconcileUncertain(data);
        setIfChanged(error, "");
        JSONObject link = gpu.optJSONObject("link");
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        String label = pcLabel(gpu);
        observeComputer(LeadModelByline.namedComputer(label) ? label : "", link, pc);
        syncModelViews(data);
        long[] heartbeats = PcHeartbeat.afterSnapshot(pc != null,
                pc != null && pc.optBoolean("live"), gpu.optBoolean("ready"),
                SystemClock.elapsedRealtime(), lastPcLiveAtMs, lastGoodPcAtMs);
        lastPcLiveAtMs = heartbeats[0];
        lastGoodPcAtMs = heartbeats[1];
        renderPairing(link);
        JSONObject phoneWork = phone.optJSONObject("answer");
        JSONObject gpuWork = gpu.optJSONObject("answer");
        pausedAfterFreshSnapshot = false;
        for (String pane : paneNames(data)) {
            if (!PaneKeys.pc(pane)) continue;
            JSONObject work = answerOf(data, pane);
            if (work != null) answerTiming.observe(pane, work.optString("state"),
                    work.optString("id"), cableConnected, observedAt(work));
            if (work == null || !"paused".equals(work.optString("state"))) continue;
            pausedAfterFreshSnapshot = true;
        }
        latestAskedSeconds = 0;
        for (String pane : paneNames(data)) {
            JSONObject work = answerOf(data, pane);
            latestAskedSeconds = Math.max(latestAskedSeconds,
                    work == null ? 0 : work.optDouble("asked", 0));
        }
        reconcileLatestRequest(data);
        if (!displayPinned) syncModelViews(data);
        if (askRecovery.unresolved()) error.setText(R.string.answer_ack_uncertain);
        else if (anyMissingIdExpired()) error.setText(R.string.answer_id_missing);
        latestQuestion = latestRequestedPanes.isEmpty()
                ? chooseQuestion(data) : lastSubmittedQuestion;
        latestQuestion = FollowUpPolicy.originalQuestion(latestQuestion, lastSubmittedQuestion);
        if (TextUtils.isEmpty(latestQuestion)) {
            setIfChanged(question, "");
            question.setVisibility(View.GONE);
        } else {
            setQuestionHeadline(question, getString(R.string.you_asked, latestQuestion));
            question.setVisibility(View.VISIBLE);
            if (!displayPinned) {
                displayedPanes.clear();
                displayedPanes.addAll(paneOrder);
                displayPinned = true;
            }
        }
        renderAnswers();
        updateModelSelectionRows();
        updateLaneRetry(data);
        archiveCompletedQuestion();
        restoreFailedDraftIfUntouched();
        renderStatus();
        updateButtons();
    }

    private static Map<String, AskRecoveryPolicy.Answer> askAnswers(
            JSONObject data, JSONArray requested) {
        Map<String, AskRecoveryPolicy.Answer> answers = new HashMap<>();
        for (int i = 0; requested != null && i < requested.length(); i++) {
            String pane = requested.optString(i);
            JSONObject work = answerOf(data, pane);
            answers.put(pane, new AskRecoveryPolicy.Answer(
                    work == null ? "" : work.optString("id"),
                    work == null ? "" : work.optString("question"),
                    work == null ? 0 : work.optDouble("asked", 0),
                    work == null ? "" : work.optString("state")));
        }
        return answers;
    }

    private void reconcileUncertain(JSONObject data) {
        if (pendingAsk == null || !askRecovery.unresolved()) return;
        AskRecoveryPolicy.Decision decision = askRecovery.beforeAsk(
                pendingAsk.retrying ? AskRecoveryPolicy.AskKind.RETRY
                        : AskRecoveryPolicy.AskKind.SEND,
                askAnswers(data, pendingAsk.requested), true);
        if (decision.next != AskRecoveryPolicy.Next.BIND) return;
        if (!pendingAsk.bound) {
            lastSubmittedQuestion = pendingAsk.question;
            rememberStarts(data, pendingAsk.requested, pendingAsk.question,
                    pendingAsk.startedAtMs, pendingAsk.submittedAtWallMs,
                    pendingAsk.retrying, pendingAsk.before,
                    new HashSet<>(decision.advancedPanes));
            pendingAsk.bound = true;
            clearDraftIfUntouched(pendingAsk.draft, pendingAsk.draftRevision);
        }
        if (decision.complete) {
            pendingAsk = null;
            askRecovery.resolve();
            getPreferences(MODE_PRIVATE).edit()
                    .putBoolean(PREF_UNRESOLVED_ASK, false).apply();
        }
    }

    private void resetAskTracking() {
        if (!askRecovery.unresolved() || acting || quitting) return;
        askRecovery.resetLocal();
        pendingAsk = null;
        getPreferences(MODE_PRIVATE).edit()
                .putBoolean(PREF_UNRESOLVED_ASK, false).apply();
        clearLatestRequest();
        answerStarts.clear();
        answerDurations.clear();
        answerFinishedAt.clear();
        answerTiming.clear();
        setIfChanged(error, "");
        if (snapshot != null) showSnapshot(snapshot);
        else updateButtons();
    }

    private String chooseQuestion(JSONObject data) {
        String selected = "";
        double newest = Double.NEGATIVE_INFINITY;
        for (String pane : paneNames(data)) {
            JSONObject work = answerOf(data, pane);
            if (work == null) continue;
            String candidate = work.optString("question");
            if (candidate.isEmpty()) continue;
            double asked = work.optDouble("asked", 0);
            if (asked > newest || asked == newest && candidate.equals(lastSubmittedQuestion)) {
                selected = candidate;
                newest = asked;
            }
        }
        return selected;
    }

    private void syncModelViews(JSONObject data) {
        for (String pane : paneNames(data)) {
            if (!PaneKeys.extra(pane)) continue;
            if (!paneViews.containsKey(pane)) paneViews.put(pane, createExtraArticle(pane));
        }
        List<String> available = paneNames(data);
        List<String> chosen = displayPinned && !displayedPanes.isEmpty()
                ? displayedPanes : PcPausePolicy.visiblePanes(paneOrder,
                laneSelection.selected(available, readyPanes(data)), cableConnected);
        List<String> desired = new ArrayList<>();
        if (chosen.contains("gpu")) desired.add("gpu");
        if (chosen.contains("phone")) desired.add("phone");
        for (String pane : available) {
            if (!chosen.contains(pane) || !PaneKeys.extra(pane)) continue;
            desired.add(pane);
        }
        for (String pane : chosen) {
            if (!PaneKeys.extra(pane) || desired.contains(pane)) continue;
            JSONObject model = paneOf(data, pane);
            if (PhoneModelGate.hidden(model == null ? pane : model.optString("label"),
                    model == null ? "" : model.optString("model"),
                    model == null ? "" : model.optString("id"),
                    model == null ? "" : model.optString("maker"))) continue;
            if (!paneViews.containsKey(pane)) paneViews.put(pane, createExtraArticle(pane));
            desired.add(pane);
        }
        if (!desired.equals(paneOrder)) {
            paneOrder.clear();
            paneOrder.addAll(desired);
            arrangeArticles();
        }
        nameGpuLane(paneViews.get("gpu"), data.optJSONObject("gpu"));
        namePhoneLane(paneViews.get("phone"), data.optJSONObject("phone"));
        for (String pane : available) {
            if (!PaneKeys.extra(pane)) continue;
            JSONObject model = paneOf(data, pane);
            PaneViews view = paneViews.get(pane);
            nameExtraLane(view, pane, model);
        }
        updateCompactLaneStatus();
    }

    private String leadReportedModel(JSONObject gpu) {
        JSONObject answer = gpu == null ? null : gpu.optJSONObject("answer");
        return LeadModelByline.reportedModel(textField(gpu, "lead_label"),
                textField(answer, "model"), answerShown("gpu", answer));
    }

    private static String pairedComputerLabel(JSONObject gpu) {
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        String label = computerLabel(link == null ? null : link.optJSONObject("pc"));
        return label.isEmpty() ? computerLabel(link == null ? null
                : link.optJSONObject("pending")) : label;
    }

    private String leadComputer(JSONObject gpu) {
        JSONObject answer = gpu == null ? null : gpu.optJSONObject("answer");
        if (answerShown("gpu", answer)) {
            String where = textField(answer, "where");
            if (LeadModelByline.namedComputer(where)) return where;
        }
        String paired = pairedComputerLabel(gpu);
        if (!paired.isEmpty()) return paired;
        String where = textField(gpu, "where");
        return LeadModelByline.namedComputer(where) ? where : "";
    }

    private String leadTitle(JSONObject gpu) {
        return LeadModelByline.title(leadComputer(gpu), leadReportedModel(gpu),
                ComputerWords.title(ComputerWords.current()));
    }

    private void nameGpuLane(PaneViews view, JSONObject gpu) {
        if (view == null) return;
        String model = leadReportedModel(gpu);
        setIfChanged(view.heading, leadTitle(gpu));
        setIfChanged(view.byline, LeadModelByline.text(leadComputer(gpu), model,
                pcWords(R.string.pc)));
    }

    /**
     * Heading and byline of an extra lane: the model that wrote the answer the card shows, else
     * the slot's current model. renderAnswers calls this again once the request and question state
     * for the snapshot are final, so its result is what is drawn.
     */
    private void nameExtraLane(PaneViews view, String pane, JSONObject model) {
        if (view == null) return;
        String slotLabel = ModelDisplay.firstNonBlank(textField(model, "label"),
                textField(model, "model"));
        if (slotLabel.isEmpty()) slotLabel = PaneKeys.fallbackLabel(pane);
        // Only an answer the card actually shows names it; a hidden older answer must not.
        String answered = answerShown(pane, model == null ? null : model.optJSONObject("answer"))
                ? answeredModel(model) : "";
        String label = AnsweredModel.label(slotLabel, answered);
        String namedModel = answered.isEmpty() ? slotLabel : answered;
        String maker = ModelMaker.maker(AnsweredModel.maker(slotLabel,
                textField(model, "maker"), answered),
                namedModel);
        String where = PaneKeys.shownWhere(pane, textField(model, "where"));
        setIfChanged(view.heading, label);
        setIfChanged(view.byline, ModelMaker.details("", maker, where));
    }

    /** Name the lead phone card from its shown answer or current model, never a hidden old answer. */
    private void namePhoneLane(PaneViews view, JSONObject phone) {
        if (view == null) return;
        JSONObject answer = phone == null ? null : phone.optJSONObject("answer");
        String reported = phone == null || phone.isNull("model") ? "" : phone.optString("model", "");
        String answered = answer == null || answer.isNull("model") ? "" : answer.optString("model", "").trim();
        // An answer the card hides must not name the card; the service's model then reads as
        // that answer's, so fall back to the place alone rather than show a stale model.
        String where = phone == null || phone.isNull("where") ? "" : phone.optString("where", "");
        boolean shown = answer != null && answerShown("phone", answer);
        setIfChanged(view.heading, PhoneByline.titleForCard(reported, answered,
                answer != null, shown, getString(R.string.phone_heading)));
        setIfChanged(view.byline, PhoneByline.forCard(reported, answered, answer != null,
                shown, PaneKeys.shownWhere("phone", where)));
    }

    private void reconcileLatestRequest(JSONObject data) {
        if (latestRequestedPanes.isEmpty()) return;
        Set<String> allowedUncertainIds = null;
        if (pendingAsk != null && askRecovery.unresolved()) {
            AskRecoveryPolicy.Decision decision = askRecovery.beforeAsk(
                    pendingAsk.retrying ? AskRecoveryPolicy.AskKind.RETRY
                            : AskRecoveryPolicy.AskKind.SEND,
                    askAnswers(data, pendingAsk.requested), true);
            allowedUncertainIds = new HashSet<>(decision.advancedPanes);
        }
        boolean changed = false;
        boolean matched = false;
        double matchedAsked = 0;
        for (String pane : latestRequestedPanes) {
            JSONObject answer = answerOf(data, pane);
            if (answer == null) continue;
            String id = answer.optString("id");
            String expected = latestRequestIds.get(pane);
            if (expected == null && !id.isEmpty()
                    && (allowedUncertainIds == null || allowedUncertainIds.contains(pane))
                    && !id.equals(previousAnswerIds.get(pane))
                    && (lastSubmittedQuestion.isEmpty()
                    || lastSubmittedQuestion.equals(answer.optString("question")))) {
                latestRequestIds.put(pane, id);
                if (questionStartedAtMs > 0) answerStarts.put(id, questionStartedAtMs);
                expected = id;
                changed = true;
            }
            if (expected != null && !id.isEmpty() && !id.equals(expected)
                    && expected.equals(laneRetryRebind.get(pane))
                    && !lastSubmittedQuestion.isEmpty()
                    && lastSubmittedQuestion.equals(answer.optString("question"))) {
                // A lane Retry whose reply was lost still reached the phone: follow the new answer.
                laneRetryRebind.remove(pane);
                latestRequestIds.put(pane, id);
                answerStarts.put(id, SystemClock.elapsedRealtime());
                laneHealth.markRetried(pane);
                expected = id;
                changed = true;
            }
            if (id.equals(expected)) {
                matched = true;
                matchedAsked = Math.max(matchedAsked, answer.optDouble("asked", 0));
                if (lastSubmittedQuestion.isEmpty()) {
                    lastSubmittedQuestion = answer.optString("question");
                    changed = true;
                }
            }
        }
        if (changed) saveLatestRequest();
        // A newer request from another client supersedes the remembered submission.
        boolean missingId = false;
        for (String pane : latestRequestedPanes) {
            if (!latestRequestIds.containsKey(pane)) missingId = true;
        }
        if (matched && !missingId && latestAskedSeconds > matchedAsked + 1) {
            clearLatestRequest();
        }
    }

    private void restoreLatestIds() {
        SharedPreferences preferences = getPreferences(MODE_PRIVATE);
        for (String pane : new String[]{"phone", "gpu", "m1", "m2", "m3", "m4",
                "g1", "g2", "g3"}) {
            String id = preferences.getString(PaneKeys.pref(pane, "latest_id"), "");
            if (id != null && !id.isEmpty()) latestRequestIds.put(pane, id);
            if (preferences.getBoolean(PaneKeys.pref(pane, "requested"),
                    latestRequestIds.containsKey(pane))) latestRequestedPanes.add(pane);
            previousAnswerIds.put(pane,
                    preferences.getString(PaneKeys.pref(pane, "previous_id"), ""));
        }
        lastSubmittedQuestion = FollowUpPolicy.originalQuestion("",
                preferences.getString("latest_question", ""));
        if (FollowUpPolicy.bareFollowUp(lastSubmittedQuestion)) lastSubmittedQuestion = "";
        latestRequestAtWallMs = preferences.getLong("latest_request_at", 0);
        long started = preferences.getLong("question_started_at", 0);
        if (started > 0 && started <= SystemClock.elapsedRealtime()) {
            questionStartedAtMs = started;
        }
        overallElapsedMs = preferences.getLong("overall_elapsed_ms", -1);
        loadTimingMap(preferences.getString("answer_durations", ""), answerDurations);
        // Start stamps are elapsedRealtime: keep only ones from this boot, so an activity
        // recreated mid-question (fold, unfold, rotation, Termux in front) still times its lanes.
        Map<String, Long> savedStarts = new HashMap<>();
        loadTimingMap(preferences.getString("answer_starts", ""), savedStarts);
        Map<String, Long> restoredStarts = AnswerStarts.onlyFollowed(AnswerStarts.sameBoot(savedStarts,
                preferences.getInt("answer_starts_boot", -1), bootCount(),
                SystemClock.elapsedRealtime()), latestRequestIds.values());
        for (Map.Entry<String, Long> entry : restoredStarts.entrySet()) {
            answerStarts.putIfAbsent(entry.getKey(), entry.getValue());
        }
        loadTimingMap(preferences.getString("answer_finished_at", ""), answerFinishedAt);
        java.util.Map<String, Long> pauseTotals = new HashMap<>();
        java.util.Map<String, Long> pauseStarts = new HashMap<>();
        loadTimingMap(preferences.getString("answer_pause_ms", ""), pauseTotals);
        loadTimingMap(preferences.getString("answer_pause_started_at", ""), pauseStarts);
        java.util.Set<String> interruptedIds = new HashSet<>();
        String interruptedRaw = preferences.getString("answer_interrupted_ids", "");
        if (interruptedRaw != null && !interruptedRaw.isEmpty()) {
            for (String id : interruptedRaw.split("\n")) {
                if (!id.isEmpty()) interruptedIds.add(id);
            }
        }
        answerTiming.restore(interruptedIds, pauseTotals, pauseStarts);
        if (!latestRequestedPanes.isEmpty()) {
            latestRequestAtElapsedMs = SystemClock.elapsedRealtime();
        }
        if (!latestRequestedPanes.isEmpty()) {
            displayedPanes.addAll(latestRequestedPanes);
            displayPinned = true;
        }
    }

    /** Settings.Global.BOOT_COUNT, or -1 when unavailable (restored starts are then dropped). */
    private int bootCount() {
        try {
            return android.provider.Settings.Global.getInt(getContentResolver(),
                    android.provider.Settings.Global.BOOT_COUNT, -1);
        } catch (RuntimeException ignored) {
            return -1;
        }
    }

    private static void loadTimingMap(String raw, Map<String, Long> into) {
        if (raw == null || raw.isEmpty()) return;
        try {
            JSONObject values = new JSONObject(raw);
            java.util.Iterator<String> keys = values.keys();
            while (keys.hasNext()) {
                String id = keys.next();
                if (!id.isEmpty()) into.put(id, values.optLong(id));
            }
        } catch (JSONException ignored) {
            // Ignore a corrupt timing cache; TONIGHT will show unmeasured.
        }
    }

    private void saveLatestRequest() {
        SharedPreferences.Editor editor = getPreferences(MODE_PRIVATE).edit();
        for (String pane : new String[]{"phone", "gpu", "m1", "m2", "m3", "m4",
                "g1", "g2", "g3"}) {
            editor.putString(PaneKeys.pref(pane, "latest_id"),
                    latestRequestIds.getOrDefault(pane, ""));
            editor.putBoolean(PaneKeys.pref(pane, "requested"),
                    latestRequestedPanes.contains(pane));
            editor.putString(PaneKeys.pref(pane, "previous_id"),
                    previousAnswerIds.getOrDefault(pane, ""));
        }
        editor.putString("latest_question", lastSubmittedQuestion)
                .putLong("latest_request_at", latestRequestAtWallMs)
                .putLong("question_started_at", questionStartedAtMs)
                .putLong("overall_elapsed_ms", overallElapsedMs);
        try {
            JSONObject durations = new JSONObject();
            for (Map.Entry<String, Long> entry : answerDurations.entrySet()) {
                if (entry.getKey() != null && entry.getValue() != null) {
                    durations.put(entry.getKey(), entry.getValue().longValue());
                }
            }
            editor.putString("answer_durations", durations.toString());
            JSONObject finished = new JSONObject();
            for (Map.Entry<String, Long> entry : answerFinishedAt.entrySet()) {
                if (entry.getKey() != null && entry.getValue() != null) {
                    finished.put(entry.getKey(), entry.getValue().longValue());
                }
            }
            editor.putString("answer_finished_at", finished.toString());
            JSONObject answerStartStamps = new JSONObject();
            for (Map.Entry<String, Long> entry : AnswerStarts.onlyFollowed(answerStarts,
                    latestRequestIds.values()).entrySet()) {
                answerStartStamps.put(entry.getKey(), entry.getValue().longValue());
            }
            editor.putString("answer_starts", answerStartStamps.toString());
            editor.putInt("answer_starts_boot", bootCount());
            JSONObject pauses = new JSONObject();
            for (Map.Entry<String, Long> entry : answerTiming.pauseTotals().entrySet()) {
                if (entry.getKey() != null && entry.getValue() != null) {
                    pauses.put(entry.getKey(), entry.getValue().longValue());
                }
            }
            editor.putString("answer_pause_ms", pauses.toString());
            JSONObject starts = new JSONObject();
            for (Map.Entry<String, Long> entry : answerTiming.pauseStarts().entrySet()) {
                if (entry.getKey() != null && entry.getValue() != null) {
                    starts.put(entry.getKey(), entry.getValue().longValue());
                }
            }
            editor.putString("answer_pause_started_at", starts.toString());
            StringBuilder interrupted = new StringBuilder();
            for (String id : answerTiming.interruptedAnswerIds()) {
                if (id == null || id.isEmpty()) continue;
                if (interrupted.length() > 0) interrupted.append('\n');
                interrupted.append(id);
            }
            editor.putString("answer_interrupted_ids", interrupted.toString());
        } catch (JSONException ignored) {
            // Timing persistence is best-effort; the on-screen ask still works.
        }
        editor.apply();
    }

    private void clearLatestRequest() {
        latestRequestIds.clear();
        latestRequestedPanes.clear();
        displayedPanes.clear();
        displayPinned = false;
        previousAnswerIds.clear();
        lastSubmittedQuestion = "";
        latestRequestAtWallMs = 0;
        latestRequestAtElapsedMs = 0;
        questionStartedAtMs = 0;
        overallElapsedMs = -1;
        answerDurations.clear();
        answerFinishedAt.clear();
        answerTiming.clear();
        saveLatestRequest();
    }

    private void hidePairingUi() {
        if (pairing != null) pairing.setVisibility(View.GONE);
        if (pairingClosed != null) pairingClosed.setVisibility(View.GONE);
        if (screen != null) {
            screen.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
        }
        pairingPending = false;
        pairingSeconds = -1;
        lastPairingSeconds = -1;
        lastPairingCode = "";
        rejectedPairingCode = "";
        pairingTimedOut = false;
        pairingActionMessage = "";
        pairingActionError = false;
        lastPairingProblem = 0;
    }

    private void renderPairing(JSONObject link) {
        JSONObject pending = link == null ? null : link.optJSONObject("pending");
        boolean closed = link != null && "closed".equals(link.optString("enrol"));
        boolean wasModalHidden = pairing.getVisibility() != View.VISIBLE;
        boolean wasClosedHidden = pairingClosed == null
                || pairingClosed.getVisibility() != View.VISIBLE;
        boolean becamePending = pending != null && !pairingPending;
        boolean showModal = PairingPrompt.showModal(pending != null);
        boolean showClosed = PairingPrompt.showClosedBanner(pending != null, closed);
        pairing.setVisibility(showModal ? View.VISIBLE : View.GONE);
        if (pairingClosed != null) {
            pairingClosed.setVisibility(showClosed ? View.VISIBLE : View.GONE);
        }
        pairingPending = pending != null;
        applyComposerState();
        if (pending != null) {
            String named = computerLabel(pending);
            // The pending computer may not be the one already paired: name it by its own label.
            String pendingNoun = ComputerWords.noun(named);
            String label = named.isEmpty() ? "the " + pendingNoun : named;
            TextView pairingHeader = findViewById(R.id.pairing_header);
            setIfChanged(pairingHeader,
                    ComputerWords.apply(getString(R.string.pairing_title), pendingNoun));
            if (allow != null) {
                setIfChanged(allow, ComputerWords.apply(getString(R.string.allow_pc), pendingNoun));
            }
            TextView disclosure = findViewById(R.id.pairing_disclosure);
            if (disclosure != null) {
                setIfChanged(disclosure,
                        ComputerWords.apply(getString(R.string.pairing_disclosure), pendingNoun));
            }
            String formatted = PairingPrompt.formatCode(
                    pending.isNull("code") ? "" : pending.optString("code"));
            pairingSeconds = PairingPrompt.secondsFromField(
                    pending.has("seconds"), pending.isNull("seconds"), pending.opt("seconds"));
            if (PairingPrompt.newRequest(!becamePending, lastPairingCode, formatted,
                    lastPairingSeconds, pairingSeconds)) {
                rejectedPairingCode = "";
                pairingTimedOut = false;
                pairingActionMessage = "";
                pairingActionError = false;
                lastPairingProblem = 0;
            }
            lastPairingCode = formatted;
            boolean validCode = PairingPrompt.validCode(formatted);
            setIfChanged(pairingCode, validCode ? formatted : "");
            pairingCode.setVisibility(validCode ? View.VISIBLE : View.GONE);
            pairingCode.setImportantForAccessibility(validCode
                    ? View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
                    : View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            pairingCode.setContentDescription(validCode
                    ? getString(R.string.pairing_code_label) + " " + PairingPrompt.spokenCode(formatted)
                    : "");
            lastPairingSeconds = pairingSeconds;
            if (PairingPrompt.expired(pairingSeconds)) pairingTimedOut = true;
            boolean rejected = !rejectedPairingCode.isEmpty()
                    && rejectedPairingCode.equals(formatted);
            int pairingProblem = pairingTimedOut ? R.string.pairing_expired
                    : rejected ? R.string.pairing_code_mismatch
                    : validCode ? 0 : R.string.pairing_code_missing;
            String allowLabel = allow == null
                    ? ComputerWords.apply(getString(R.string.allow_pc), pendingNoun)
                    : allow.getText().toString();
            String request = getString(R.string.pairing_request, label, allowLabel);
            String message = pairingProblem != 0 ? getString(pairingProblem)
                    : pairingActionMessage.isEmpty() ? request : pairingActionMessage;
            setIfChanged(pairingText, message);
            pairingText.setTextColor(parseHex(pairingTimedOut || rejected || pairingActionError
                    ? palette.error() : palette.ink()));
            if (!becamePending && pairingProblem != 0 && pairingProblem != lastPairingProblem) {
                pairing.announceForAccessibility(message);
            }
            lastPairingProblem = pairingProblem;
            if (pairingCountdown != null) {
                String countdown = PairingPrompt.countdownText(pairingSeconds,
                        getString(R.string.pairing_countdown),
                        getString(R.string.pairing_expired_short));
                setIfChanged(pairingCountdown, countdown);
                pairingCountdown.setVisibility(countdown.isEmpty() ? View.GONE : View.VISIBLE);
                applyPairingCountdownTone();
            }
            if (pairingHeader != null) {
                String description = pairingHeader.getText().toString();
                if (validCode) description += " " + pairingCode.getContentDescription();
                if (!TextUtils.equals(pairingHeader.getContentDescription(), description)) {
                    pairingHeader.setContentDescription(description);
                }
            }
        } else if (closed) {
            pairingSeconds = -1;
            setIfChanged(findViewById(R.id.pairing_closed_header),
                    getString(R.string.pairing_closed_title));
            setIfChanged(findViewById(R.id.pairing_closed_text), pcWords(R.string.pairing_closed));
        } else {
            pairingSeconds = -1;
        }
        if (pending == null && screen != null) {
            screen.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
        }
        if (pending == null) {
            String finalProblem = pairingTimedOut ? getString(R.string.pairing_expired)
                    : !rejectedPairingCode.isEmpty() ? getString(R.string.pairing_code_mismatch)
                    : pairingActionError ? pairingActionMessage : "";
            if (!finalProblem.isEmpty()) setIfChanged(error, finalProblem);
            pairingTimedOut = false;
            rejectedPairingCode = "";
            lastPairingCode = "";
            lastPairingSeconds = -1;
            pairingActionMessage = "";
            pairingActionError = false;
            lastPairingProblem = 0;
        }
        if (becamePending) {
            hideKeyboard();
            applyPairingTypography();
            TextView pairingHeader = findViewById(R.id.pairing_header);
            if (pairingHeader != null) {
                pairingHeader.post(() -> pairingHeader.performAccessibilityAction(
                        AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS, null));
            }
        }
        if (screen != null) {
            screen.setImportantForAccessibility(showModal
                    ? View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
                    : View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
        }
        if (showClosed && wasClosedHidden && pairingClosed != null
                && pairingClosed.getVisibility() == View.VISIBLE) {
            resultsScroll.post(() -> resultsScroll.smoothScrollTo(0, 0));
        }
    }

    private void applyPairingTypography() {
        if (pairing == null) return;
        TextView header = findViewById(R.id.pairing_header);
        if (header != null) {
            typography.headline(header, typography.headingSp());
            header.setFocusable(true);
        }
        if (pairingText != null) typography.body(pairingText, typography.bodySp());
        TextView codeLabel = findViewById(R.id.pairing_code_label);
        if (codeLabel != null) typography.kicker(codeLabel);
        int codeSp = PairingPrompt.codeSizeSp(coverMode);
        if (pairingCode != null) {
            typography.display(pairingCode, codeSp);
            typography.tabular(pairingCode);
            typography.applyLineHeight(pairingCode, codeSp, 1.1f);
        }
        if (pairingCountdown != null) typography.state(pairingCountdown);
        TextView disclosure = findViewById(R.id.pairing_disclosure);
        if (disclosure != null) typography.body(disclosure, typography.bodySp());
        if (allow != null) typography.headline(allow, typography.headingSp());
        if (deny != null) typography.retry(deny);
        if (allow != null) {
            setMinHeightPx(allow, dp(PairingPrompt.allowMinHeightDp(coverMode)));
        }
        if (deny != null) {
            setMinHeightPx(deny, dp(PairingPrompt.denyMinHeightDp(coverMode)));
        }
        int pad = dp(PairingPrompt.paddingDp(coverMode));
        View body = findViewById(R.id.pairing_body);
        if (body != null) body.setPadding(pad, pad, pad, pad);
        View actions = findViewById(R.id.pairing_actions);
        if (actions != null) actions.setPadding(pad, dp(coverMode ? 4 : 8), pad, pad);
        layoutPairingForScreen(codeLabel, disclosure, actions);
        if (pairingClosed != null) {
            TextView closedHeader = findViewById(R.id.pairing_closed_header);
            TextView closedText = findViewById(R.id.pairing_closed_text);
            if (closedHeader != null) typography.headline(closedHeader, typography.headingSp());
            if (closedText != null) typography.body(closedText, typography.bodySp());
            if (reopen != null) typography.retry(reopen);
        }
    }

    /** Cover: tighter gaps and Allow / Not now in one row so nothing runs under the buttons. */
    private void layoutPairingForScreen(TextView codeLabel, TextView disclosure, View actions) {
        int gap = dp(PairingPrompt.gapDp(coverMode));
        setTopMargin(codeLabel, coverMode ? gap : dp(24));
        setTopMargin(disclosure, gap);
        if (!(actions instanceof LinearLayout) || allow == null || deny == null) return;
        boolean row = PairingPrompt.actionsSideBySide(coverMode);
        ((LinearLayout) actions).setOrientation(row ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        LinearLayout.LayoutParams allowParams = row
                ? new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                : new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT);
        LinearLayout.LayoutParams denyParams = row
                ? new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                : new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT);
        if (row) denyParams.leftMargin = dp(8);
        else denyParams.topMargin = dp(8);
        allow.setLayoutParams(allowParams);
        deny.setLayoutParams(denyParams);
    }

    private static void setTopMargin(View view, int px) {
        if (view == null || !(view.getLayoutParams() instanceof ViewGroup.MarginLayoutParams)) return;
        ViewGroup.MarginLayoutParams params = (ViewGroup.MarginLayoutParams) view.getLayoutParams();
        if (params.topMargin == px) return;
        params.topMargin = px;
        view.setLayoutParams(params);
    }

    private void applyPairingCountdownTone() {
        if (pairingCountdown == null) return;
        int color = themeColor(PairingPrompt.expired(pairingSeconds)
                ? R.color.newspaper_error
                : R.color.newspaper_ink);
        pairingCountdown.setTextColor(color);
    }

    private static void setMinHeightPx(View view, int px) {
        if (view instanceof TextView) {
            ((TextView) view).setMinHeight(px);
            ((TextView) view).setMinimumHeight(px);
        } else {
            view.setMinimumHeight(px);
        }
        ViewGroup.LayoutParams lp = view.getLayoutParams();
        if (lp != null) {
            lp.height = px;
            view.setLayoutParams(lp);
        }
    }

    private void renderAnswers() {
        if (snapshot == null) return;
        JSONObject gpu = snapshot.optJSONObject("gpu");
        if (snapshot.optJSONObject("phone") == null || gpu == null) return;
        PageAnchor snapshotAnchor = capturePageAnchor();
        for (String pane : paneOrder) {
            JSONObject view = paneOf(snapshot, pane);
            PaneViews article = paneViews.get(pane);
            if (view != null && article != null) {
                if ("gpu".equals(pane)) nameGpuLane(article, view);
                if (PaneKeys.extra(pane)) nameExtraLane(article, pane, view);
                if ("phone".equals(pane)) namePhoneLane(article, view);
                renderPane(article, view, PaneKeys.pc(pane)
                        ? gpu.optJSONObject("link") : null);
            } else if (article != null && PaneKeys.extra(pane)) {
                setLiveSpeed(article, "");
            }
        }
        updateSummary();
        updateCompactLaneStatus();
        restorePageAnchor(snapshotAnchor);
    }

    private static final class PageAnchor {
        final int scrollY;
        final int index;
        final int anchorTop;
        final int[] tops;

        PageAnchor(int scrollY, int index, int anchorTop, int[] tops) {
            this.scrollY = scrollY;
            this.index = index;
            this.anchorTop = anchorTop;
            this.tops = tops;
        }
    }

    private int yInScrollContent(View view) {
        int y = 0;
        View current = view;
        while (current != null && current != resultsScroll) {
            y += current.getTop();
            if (!(current.getParent() instanceof View)) break;
            current = (View) current.getParent();
        }
        return y;
    }

    private int[] pageCardEdges(boolean bottoms) {
        java.util.ArrayList<View> cards = new java.util.ArrayList<>();
        for (String pane : paneOrder) {
            PaneViews article = paneViews.get(pane);
            if (article != null && article.card.getParent() != null) cards.add(article.card);
        }
        if (timingCard != null && timingCard.getParent() != null) cards.add(timingCard);
        if (notesCard != null && notesCard.getParent() != null) cards.add(notesCard);
        if (summaryCard != null && summaryCard.getParent() != null) cards.add(summaryCard);
        cards.sort((left, right) -> Integer.compare(yInScrollContent(left), yInScrollContent(right)));
        int[] edges = new int[cards.size()];
        for (int i = 0; i < cards.size(); i++) {
            View card = cards.get(i);
            int top = yInScrollContent(card);
            edges[i] = bottoms ? top + card.getHeight() : top;
        }
        return edges;
    }

    private PageAnchor capturePageAnchor() {
        if (resultsScroll == null) return null;
        int[] bottoms = pageCardEdges(true);
        int[] tops = pageCardEdges(false);
        int scrollY = resultsScroll.getScrollY();
        int index = PageScrollAnchor.pickAnchorIndex(scrollY, bottoms);
        int anchorTop = (index >= 0 && index < tops.length) ? tops[index] : 0;
        return new PageAnchor(scrollY, index, anchorTop, tops);
    }

    private void restorePageAnchor(PageAnchor anchor) {
        if (anchor == null || resultsScroll == null) return;
        Runnable apply = () -> {
            int[] newTops = pageCardEdges(false);
            if (newTops.length == 0) return;
            int newTop = anchor.index < newTops.length ? newTops[anchor.index] : newTops[0];
            View content = resultsScroll.getChildCount() > 0 ? resultsScroll.getChildAt(0) : null;
            int contentHeight = content == null ? 0 : content.getHeight();
            int max = ScrollPolicy.maxScroll(contentHeight, resultsScroll.getHeight(),
                    resultsScroll.getPaddingTop(), resultsScroll.getPaddingBottom());
            int next = PageScrollAnchor.adjust(anchor.scrollY, anchor.anchorTop, newTop, max);
            boolean headlineShown = question != null && question.getVisibility() == View.VISIBLE
                    && !TextUtils.isEmpty(question.getText());
            int headlineTop = headlineShown ? yInScrollContent(question) : 0;
            next = CoverScreenPolicy.keepHeadlineVisible(next, headlineTop, coverMode, headlineShown);
            if (next != resultsScroll.getScrollY()) resultsScroll.scrollTo(0, next);
            setHeaderCollapse(resultsScroll.getScrollY());
        };
        resultsScroll.post(apply);
        if (!reduceMotionEnabled) {
            resultsScroll.postDelayed(apply, LaneCardLayout.GROW_MS);
        }
    }

    private void plainArticle(PaneViews article, String text) {
        article.renderedAnswerId = "";
        article.rawAnswer = "";
        article.words = 0;
        article.follow.reset();
        article.lastRenderedState = "";
        article.userScrolled = false;
        setPlainAnswer(article.answer, text);
        setLiveSpeed(article, "");
        if (article.bodyScroll != null) {
            article.programmaticScroll = true;
            article.bodyScroll.scrollTo(0, 0);
            article.programmaticScroll = false;
        }
        updateExpanded(article);
    }

    private void setWaitingLayout(PaneViews article, boolean waiting) {
        if (!PaneKeys.extra(article.pane)) return;
        setVisibilityIfNeeded(article.kicker, LaneCardLayout.waitingVisible(
                waiting, LaneCardLayout.Part.KICKER) ? View.VISIBLE : View.GONE);
        setVisibilityIfNeeded(article.heading, LaneCardLayout.waitingVisible(
                waiting, LaneCardLayout.Part.HEADING) ? View.VISIBLE : View.GONE);
        setVisibilityIfNeeded(article.answer, LaneCardLayout.waitingVisible(
                waiting, LaneCardLayout.Part.ANSWER) ? View.VISIBLE : View.GONE);
    }

    private void setLiveSpeed(PaneViews article, String speed) {
        setIfChanged(article.speed, speed);
        setVisibilityIfNeeded(article.speed, speed.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private static void setVisibilityIfNeeded(View view, int visibility) {
        if (view.getVisibility() != visibility) view.setVisibility(visibility);
    }

    private void clearNewspaperContent() {
        for (PaneViews article : paneViews.values()) {
            article.renderedAnswerId = "";
            article.rawAnswer = "";
            article.words = 0;
            article.follow.reset();
            setPlainAnswer(article.answer, "");
            setLiveSpeed(article, "");
            updateExpanded(article);
        }
        setSummaryReport("");
        setTonightTiming("");
        setIfChanged(tonightCount, "—");
        setIfChanged(tonightProvenance, "");
    }

    /**
     * Whether renderPane shows this answer's text (rather than "Not asked this time" or a waiting
     * state). Keep in step with the guards at the top of renderPane.
     */
    private boolean answerShown(String paneName, JSONObject answer) {
        if (answer == null) return false;
        if (!latestRequestedPanes.isEmpty()) {
            String expectedId = latestRequestIds.get(paneName);
            if (!latestRequestedPanes.contains(paneName) || expectedId == null
                    || !expectedId.equals(answer.optString("id"))) return false;
        }
        String answerQuestion = answer.optString("question");
        if (!TextUtils.isEmpty(latestQuestion) && !TextUtils.isEmpty(answerQuestion)
                && !latestQuestion.equals(answerQuestion)) return false;
        return !(latestRequestedPanes.isEmpty() && latestAskedSeconds > 0
                && answer.optDouble("asked", 0) + 1 < latestAskedSeconds);
    }

    private void renderPane(PaneViews article, JSONObject pane, JSONObject link) {
        String paneName = article.pane;
        boolean isGpu = PaneKeys.pc(paneName);
        boolean extra = PaneKeys.extra(paneName);
        TextView stateView = article.state;
        JSONObject answer = pane.optJSONObject("answer");
        if (!latestRequestedPanes.isEmpty()) {
            if (!latestRequestedPanes.contains(paneName)) {
                setWaitingLayout(article, false);
                setLaneState(stateView, article.card, getString(R.string.not_asked_this_time));
                plainArticle(article, getString(R.string.not_asked_detail));
                return;
            }
            String expectedId = latestRequestIds.get(paneName);
            if (expectedId == null || answer == null) {
                int message = missingIdExpired(paneName)
                        ? R.string.answer_id_missing : extra
                        ? R.string.waiting_turn : R.string.thinking;
                String answerState = answer == null ? "waiting" : answer.optString("state");
                boolean pcPaused = !missingIdExpired(paneName)
                        && PcPausePolicy.paused(paneName, answerState, cableConnected);
                if (pcPaused) {
                    message = R.string.gpu_paused;
                } else if (isGpu && open(answer) && awaitingReplugSnapshot) {
                    message = R.string.cable_checking;
                }
                setLaneState(stateView, article.card, pcWords(message));
                setWaitingLayout(article, extra && message == R.string.waiting_turn);
                if (!pcPaused) plainArticle(article, "");
                else setLiveSpeed(article, "");
                return;
            }
            if (!expectedId.equals(answer.optString("id"))) {
                setWaitingLayout(article, false);
                setLaneState(stateView, article.card, getString(R.string.not_asked_this_time));
                plainArticle(article, getString(R.string.not_asked_detail));
                return;
            }
        }
        if (answer == null) {
            setWaitingLayout(article, false);
            String state;
            if (isGpu) {
                JSONObject pc = link == null ? null : link.optJSONObject("pc");
                state = link == null ? pcWords(R.string.gpu_unavailable)
                        : pc == null ? pcWords(R.string.connect_pc)
                        : pane.optBoolean("ready") ? getString(R.string.ready_to_ask)
                        : pcWords(R.string.waiting_for_pc);
            } else {
                state = pane.optBoolean("ready") ? getString(R.string.ready_to_ask)
                        : getString(R.string.phone_model_unavailable);
            }
            setLaneState(stateView, article.card, state);
            plainArticle(article, getString(R.string.empty_answer));
            return;
        }
        String answerQuestion = answer.optString("question");
        if (!TextUtils.isEmpty(latestQuestion) && !TextUtils.isEmpty(answerQuestion)
                && !latestQuestion.equals(answerQuestion)) {
            setWaitingLayout(article, false);
            setLaneState(stateView, article.card, getString(R.string.not_asked_this_time));
            plainArticle(article, getString(R.string.not_asked_detail));
            return;
        }
        String state = answer.optString("state");
        String id = answer.optString("id");
        if (latestRequestedPanes.isEmpty() && latestAskedSeconds > 0
                && answer.optDouble("asked", 0) + 1 < latestAskedSeconds) {
            setWaitingLayout(article, false);
            setLaneState(stateView, article.card, getString(R.string.not_asked_this_time));
            plainArticle(article, getString(R.string.not_asked_detail));
            return;
        }
        if (("done".equals(state) || "failed".equals(state) || "cancelled".equals(state))
                && answerStarts.containsKey(id)
                && !answerDurations.containsKey(id)) {
            long finishedAt = observedAt(answer);
            answerDurations.put(id, Math.max(0, finishedAt - answerStarts.get(id)));
            answerFinishedAt.put(id, finishedAt);
            saveLatestRequest();
        }
        boolean sameRenderedAnswer = id.equals(article.renderedAnswerId);
        if (!sameRenderedAnswer) {
            article.renderedAnswerId = id;
            article.rawAnswer = "";
            article.words = 0;
            article.follow.reset();
            article.userScrolled = false;
            article.lastRenderedState = "";
            setPlainAnswer(article.answer, "");
            if (article.bodyScroll != null) {
                article.programmaticScroll = true;
                article.bodyScroll.scrollTo(0, 0);
                article.programmaticScroll = false;
            }
        }
        String answerText = AnswerDisplay.text(paneName, PcPausePolicy.textToDisplay(
                paneName, state, sameRenderedAnswer, article.rawAnswer, answer.optString("text")));
        String failureCode = answer.optString("error", answer.optString("code"));
        String stateWords = "answering".equals(state) && answerText.isEmpty()
                ? getString(R.string.thinking)
                : answerWords(paneName, state, id, answerText, failureCode);
        boolean pcPaused = PcPausePolicy.paused(paneName, state, cableConnected);
        if (pcPaused) {
            stateWords = pcWords(R.string.gpu_paused);
        } else if (isGpu && awaitingReplugSnapshot && open(answer)) {
            stateWords = pcWords(R.string.cable_checking);
        }
        if (extra) {
            setLiveSpeed(article, LiveSpeedLabel.text(pane.opt("live_speed"), state,
                    answerShown(paneName, answer), stateWords, getString(R.string.streaming)));
        }
        setLaneState(stateView, article.card, stateWords);
        if (extra && ("queued".equals(state) || "waiting".equals(state)
                || "loading".equals(state)) && !pcPaused) {
            setWaitingLayout(article, true);
            plainArticle(article, "");
            return;
        }
        setWaitingLayout(article, false);
        if ("failed".equals(state) && ("low_memory".equals(answerText)
                || "model_start".equals(answerText))) answerText = "";
        if (!answerText.equals(article.rawAnswer)) {
            article.rawAnswer = answerText;
            article.words = NewspaperSummary.wordCount(answerText);
        }
        boolean reachedDone = "done".equals(state)
                && !"done".equals(article.lastRenderedState);
        boolean reachedPaused = pcPaused && !"paused".equals(article.lastRenderedState);
        article.lastRenderedState = pcPaused ? "paused" : state;
        boolean textChanged = !answerText.equals(article.answer.getTag());
        if (textChanged) {
            setMarkdownAnswer(article.answer, answerText);
        }
        alignArticleScroll(article, textChanged, reachedDone, reachedPaused);
        updateExpanded(article);
        updateWorking(article);
    }

    private String answerWords(String pane, String state, String id,
                               String answerText, String errorCode) {
        boolean isGpu = PaneKeys.pc(pane);
        if (laneHealth.garbled(pane, id) || "garbled".equals(errorCode)
                || AnswerGuard.reason(answerText) != null) {
            return pcWords(AnswerFailureLabel.resource(isGpu, answerText, "garbled"));
        }
        switch (state) {
            case "queued":
            case "waiting":
            case "loading":
                return PaneKeys.extra(pane) ? getString(R.string.waiting_turn)
                        : getString(R.string.thinking);
            case "answering":
                return getString(R.string.streaming);
            case "paused":
                // A phone lane pauses for a backend restart, not for the cable or the computer.
                return isGpu ? pcWords(R.string.gpu_paused) : getString(R.string.lane_paused);
            case "done":
                Long duration = answerDurations.get(id);
                boolean interrupted = isGpu && answerTiming.interrupted(id);
                long pauseMs = isGpu ? answerTiming.pauseMs(id, SystemClock.elapsedRealtime()) : 0;
                boolean pauseMeasured = isGpu && answerTiming.pauseMeasured(id);
                return AnswerTimingPolicy.doneLabel(duration, pauseMs, interrupted, pauseMeasured);
            case "cancelled":
                return getString(R.string.answer_stopped);
            case "failed":
                if ("low_memory".equals(errorCode) || "low_memory".equals(answerText)) {
                    return getString(R.string.model_low_memory);
                }
                if ("model_start".equals(errorCode) || "model_start".equals(answerText)) {
                    return getString(R.string.model_start_failed);
                }
                return pcWords(AnswerFailureLabel.resource(isGpu, answerText, errorCode));
            default:
                return getString(R.string.answer_waiting);
        }
    }

    private void updateSummary() {
        List<NewspaperSummary.Lane> lanes = new ArrayList<>();
        boolean allClosed = !latestRequestedPanes.isEmpty();
        boolean anyInterrupted = false;
        for (String pane : orderedDevicePanes()) {
            PaneViews article = paneViews.get(pane);
            if (article == null) continue;
            JSONObject answer = answerOf(snapshot, pane);
            String id = answer == null ? "" : answer.optString("id");
            String shortLabel = article.heading.getText().toString();
            boolean included = latestRequestedPanes.isEmpty()
                    ? answer != null && !latestQuestion.isEmpty()
                    && latestQuestion.equals(answer.optString("question"))
                    : latestRequestedPanes.contains(pane)
                    && (latestRequestIds.get(pane) == null
                    || id.equals(latestRequestIds.get(pane)));
            boolean currentId = latestRequestedPanes.isEmpty()
                    || id.equals(latestRequestIds.get(pane));
            boolean interrupted = included && currentId && PaneKeys.pc(pane)
                    && answerTiming.interrupted(id);
            anyInterrupted |= interrupted;
            long nowMs = SystemClock.elapsedRealtime();
            long pauseMs = PaneKeys.pc(pane) ? answerTiming.pauseMs(id, nowMs) : 0;
            boolean pauseMeasured = PaneKeys.pc(pane) && answerTiming.pauseMeasured(id);
            Long duration = included && currentId
                    ? AnswerTimingPolicy.displayDuration(answerDurations.get(id), pauseMs,
                            interrupted, pauseMeasured) : null;
            Long finishedAt = included && currentId
                    ? AnswerTimingPolicy.comparisonFinish(answerFinishedAt.get(id))
                    : null;
            boolean pending = included && ((latestRequestedPanes.contains(pane)
                    && latestRequestIds.get(pane) == null && !missingIdExpired(pane))
                    || currentId && open(answer));
            String stateText = article.state.getText().toString();
            String marker = included && currentId
                    ? AnswerTimingPolicy.rowMarker(stateText, interrupted, pauseMeasured) : null;
            if (marker == null && included && currentId && duration == null && !pending) {
                if (ErrorCopy.errorLine(stateText)) marker = "failed";
                else if (stateText.startsWith("Done")) marker = "unmeasured";
            }
            lanes.add(new NewspaperSummary.Lane(shortLabel, article.rawAnswer,
                    stateText, duration, finishedAt,
                    included, article.words, pending, marker, interrupted));
        }
        for (String pane : latestRequestedPanes) {
            JSONObject answer = answerOf(snapshot, pane);
            String expectedId = latestRequestIds.get(pane);
            boolean pendingId = expectedId == null && !missingIdExpired(pane);
            boolean pendingAnswer = expectedId != null
                    && (answer == null || !expectedId.equals(answer.optString("id"))
                    || open(answer));
            if (pendingId || pendingAnswer) allClosed = false;
        }
        setTonightTiming(NewspaperSummary.timing(lanes), lanes);
        setIfChanged(tonightProvenance, AnswerTimingPolicy.overallLabel(anyInterrupted));
        applyTone(tonightProvenance);
        if (questionStartedAtMs <= 0) setIfChanged(tonightCount, "—");
        else {
            long elapsed = allClosed && overallElapsedMs >= 0 ? overallElapsedMs
                    : Math.max(0, SystemClock.elapsedRealtime() - questionStartedAtMs);
            if (allClosed) {
                // Freeze the total at the last lane's finish, not at "now": after an app
                // restart the first closed render can be minutes later. Lane finish times are
                // elapsedRealtime stamps, so measure from the question start, and correct any
                // stored total that disagrees (self-heals totals saved by older builds).
                Long total = NewspaperSummary.totalFromFinishes(lanes, questionStartedAtMs);
                if (total == null && overallElapsedMs < 0) total = elapsed;
                if (total != null && total != overallElapsedMs) {
                    overallElapsedMs = total;
                    saveLatestRequest();
                }
                elapsed = overallElapsedMs;
            }
            setIfChanged(tonightCount, NewspaperSummary.seconds(elapsed));
        }
        setSummaryReport(NewspaperSummary.report(lanes));
    }

    private void archiveCompletedQuestion() {
        if (snapshot == null || latestRequestAtWallMs <= 0 || lastSubmittedQuestion.isEmpty()
                || latestRequestedPanes.isEmpty()) return;
        String issueId = Long.toString(latestRequestAtWallMs);
        if (issueId.equals(archivedIssueId) || issueId.equals(suppressedIssueId)) return;
        List<HistoryStore.Lane> lanes = new ArrayList<>();
        boolean anyInterrupted = false;
        for (String pane : orderedDevicePanes()) {
            if (!latestRequestedPanes.contains(pane)) continue;
            JSONObject answer = answerOf(snapshot, pane);
            String expectedId = latestRequestIds.get(pane);
            if (answer == null || expectedId == null || expectedId.isEmpty()
                    || !expectedId.equals(answer.optString("id"))
                    || !lastSubmittedQuestion.equals(answer.optString("question"))) return;
            String state = answer.optString("state");
            if (!"done".equals(state) && !"failed".equals(state)
                    && !"cancelled".equals(state)) return;
            PaneViews article = paneViews.get(pane);
            JSONObject model = paneOf(snapshot, pane);
            if (article == null) return;
            String label = article.heading.getText().toString();
            // Keep the model that wrote this answer, even if the slot now holds another one.
            String answerModel = textField(answer, "model");
            String slotLabel = textField(model, "label");
            String slotModel = textField(model, "model");
            String slotMaker = textField(model, "maker");
            String resolvedModel = answerModel.isEmpty()
                    ? ModelDisplay.firstNonBlank(PaneKeys.extra(pane) ? slotLabel : "", slotModel)
                    : answerModel;
            PhoneByline.ArchiveName phoneName = "phone".equals(pane)
                    ? PhoneByline.archived(answerModel, slotModel, getString(R.string.phone_heading))
                    : null;
            String maker = phoneName != null ? phoneName.maker
                    : ModelMaker.maker(AnsweredModel.maker(
                            PaneKeys.extra(pane) ? slotLabel : slotModel,
                            slotMaker, answerModel), resolvedModel);
            if (phoneName != null) {
                label = phoneName.title;
            } else if (PaneKeys.extra(pane)) {
                label = AnsweredModel.label(label, answerModel);
            } else if ("gpu".equals(pane)) {
                if (!resolvedModel.isEmpty()) label = ModelDisplay.label(resolvedModel);
            }
            String where = PaneKeys.shownWhere(pane,
                    model == null || model.isNull("where") ? "" : model.optString("where"));
            boolean interrupted = PaneKeys.pc(pane) && answerTiming.interrupted(expectedId);
            anyInterrupted |= interrupted;
            long pauseMs = PaneKeys.pc(pane)
                    ? answerTiming.pauseMs(expectedId, SystemClock.elapsedRealtime()) : 0;
            boolean pauseMeasured = PaneKeys.pc(pane) && answerTiming.pauseMeasured(expectedId);
            lanes.add(new HistoryStore.Lane(pane, label, maker, where,
                    article.state.getText().toString(), article.rawAnswer,
                    AnswerTimingPolicy.archivedDuration(answerDurations.get(expectedId),
                            pauseMs, interrupted, pauseMeasured)));
        }
        if (lanes.size() != latestRequestedPanes.size()) return;
        String sourceId = "";
        if (!pendingRefreshSourceId.isEmpty()
                && pendingRefreshQuestion.equals(lastSubmittedQuestion)) {
            sourceId = pendingRefreshSourceId;
        }
        try {
            historyStore.upsert(new HistoryStore.Issue(issueId, latestRequestAtWallMs,
                    lastSubmittedQuestion, tonightTiming.getText().toString(),
                    tonightCount.getText().toString(), lanes, anyInterrupted, sourceId));
        } catch (IllegalArgumentException failure) {
            error.setText("Could not save this question to History.");
        }
        if (pendingRefreshQuestion.equals(lastSubmittedQuestion)) {
            pendingRefreshSourceId = "";
            pendingRefreshQuestion = "";
        }
        archivedIssueId = issueId;
    }

    private void renderStatus() {
        if (!reachable || snapshot == null) {
            // No fresh snapshot: never claim CONNECTED, but keep the pause banner for work on screen.
            renderLinkBanner(false, hasVisiblePcWork());
            return;
        }
        JSONObject phone = snapshot.optJSONObject("phone");
        JSONObject gpu = snapshot.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        JSONObject pending = link == null ? null : link.optJSONObject("pending");
        JSONObject phoneWork = phone == null ? null : phone.optJSONObject("answer");
        JSONObject gpuWork = gpu == null ? null : gpu.optJSONObject("answer");
        boolean extraOpen = false;
        boolean pcOpen = false;
        boolean streaming = false;
        for (String pane : paneNames(snapshot)) {
            JSONObject work = answerOf(snapshot, pane);
            if (PaneKeys.extra(pane) && open(work)) extraOpen = true;
            if (PaneKeys.pc(pane) && open(work)) pcOpen = true;
            if (work != null && "answering".equals(work.optString("state"))) streaming = true;
        }
        Connection connection = pcConnection(gpu);
        AnswerOutcome.Result outcome = AnswerOutcome.visible(
                currentAnswerOutcome(), connection == Connection.CONNECTED);
        if (stopWaitingForId && !StopPolicy.noIdStillOpen(
                anyBlockingOpen(), openAnswerIdsByPane(snapshot))) {
            stopWaitingForId = false;
        }
        String line;
        if (Boolean.FALSE.equals(cableConnected)) {
            line = pcOpen || hasVisiblePcWork() ? getString(R.string.paused_plug_cable)
                    : getString(R.string.info_usb_disconnected);
        } else if (awaitingReplugSnapshot) {
            line = pcWords(R.string.cable_checking);
        } else if (pending != null) {
            line = ComputerWords.apply(getString(R.string.pairing_pending),
                    ComputerWords.noun(computerLabel(pending)));
        } else if (pausedAfterFreshSnapshot) {
            line = pcWords(R.string.gpu_paused);
        } else if (stopWaitingForId) {
            line = getString(R.string.stop_not_ready);
        } else if (awaitingAnswerId()) {
            line = getString(R.string.thinking);
        } else if (open(gpuWork) && connection == Connection.DISCONNECTED
                && !streaming) {
            line = pcWords(R.string.waiting_for_pc);
        } else if (streaming) {
            line = getString(R.string.streaming);
        } else if (open(phoneWork) || open(gpuWork) || extraOpen) {
            line = getString(R.string.thinking);
        } else if (connection == Connection.CONNECTED && cableConnected == null) {
            line = pcWords(R.string.cable_checking);
        } else if (outcome == AnswerOutcome.Result.FAILED) {
            line = getString(R.string.answers_failed);
        } else if (outcome == AnswerOutcome.Result.STOPPED) {
            line = getString(R.string.answer_stopped);
        } else if (outcome == AnswerOutcome.Result.FINISHED) {
            line = getString(R.string.answer_done);
        } else if (connection == Connection.CONNECTED) {
            line = getString(R.string.ready_to_ask);
        } else if (connection == Connection.PREPARING) {
            line = pcWords(R.string.pc_getting_ready);
        } else if (pc != null) {
            line = pcWords(R.string.waiting_for_pc);
        } else if (link != null && "closed".equals(link.optString("enrol"))) {
            line = getString(R.string.pairing_closed_title);
        } else if (link != null) {
            line = pcWords(R.string.connect_pc);
        } else {
            line = pcWords(R.string.gpu_unavailable);
        }
        setMainStatus(line);
        renderLinkBanner(connection == Connection.CONNECTED, pcOpen || hasVisiblePcWork());
        if (infoDialog != null && infoDialog.isShowing()) {
            updateInfoPcRows(infoDialog, gpu, connection);
        }
        applyErrorView();
    }

    private void setupDeviceBand() {
        deviceBand = findViewById(R.id.device_band);
        devicePhone = findViewById(R.id.device_phone);
        deviceComputer = findViewById(R.id.device_computer);
        devicePhoneKicker = findViewById(R.id.device_phone_kicker);
        devicePhoneName = findViewById(R.id.device_phone_name);
        deviceComputerKicker = findViewById(R.id.device_computer_kicker);
        deviceComputerName = findViewById(R.id.device_computer_name);
        deviceLink = findViewById(R.id.device_link);
        String configuredName = null;
        try {
            configuredName = Settings.Global.getString(getContentResolver(), "device_name");
        } catch (RuntimeException ignored) {
            // The model still identifies the phone when its saved device name is unavailable.
        }
        setIfChanged(devicePhoneName, DeviceLayoutPolicy.phoneName(configuredName, Build.MODEL));
        deviceBand.setContentDescription(DeviceLayoutPolicy.description(
                devicePhoneName.getText().toString(),
                ComputerWords.title(ComputerWords.current()), deviceLinkState));
        applyDeviceBandMode();
    }

    private void applyDeviceBandMode() {
        if (deviceBand == null) return;
        devicePhoneKicker.setVisibility(coverMode ? View.GONE : View.VISIBLE);
        deviceComputerKicker.setVisibility(coverMode ? View.GONE : View.VISIBLE);
        for (LinearLayout panel : new LinearLayout[]{devicePhone, deviceComputer}) {
            panel.setMinimumHeight(dp(coverMode ? 44 : 64));
            int pad = dp(coverMode ? 6 : 8);
            panel.setPadding(pad, pad, pad, pad);
        }
    }

    private void renderDeviceBand(boolean linkConnected) {
        if (deviceBand == null) return;
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        JSONObject pending = link == null ? null : link.optJSONObject("pending");
        String name = computerLabel(pc);
        if (name.isEmpty()) name = computerLabel(pending);
        if (name.isEmpty()) name = ComputerWords.title(ComputerWords.current());
        boolean errorState = offline || pc != null && "error".equals(pc.optString("state"));
        deviceLinkState = DeviceLayoutPolicy.linkState(cableConnected, linkConnected,
                pausedAfterFreshSnapshot, errorState);
        setIfChanged(deviceComputerName, name);
        setIfChanged(deviceLink, DeviceLayoutPolicy.linkLabel(deviceLinkState));
        String description = DeviceLayoutPolicy.description(
                devicePhoneName.getText().toString(), name, deviceLinkState);
        if (!TextUtils.equals(deviceBand.getContentDescription(), description)) {
            deviceBand.setContentDescription(description);
        }
        styleDeviceBand();
    }

    private void styleDeviceBand() {
        if (deviceBand == null) return;
        devicePhone.setBackground(panelDrawable(palette.stroke()));
        deviceComputer.setBackground(panelDrawable(palette.stroke()));
        devicePhoneKicker.setTextColor(parseHex(palette.label()));
        deviceComputerKicker.setTextColor(parseHex(palette.label()));
        devicePhoneName.setTextColor(parseHex(palette.ink()));
        deviceComputerName.setTextColor(parseHex(palette.ink()));
        deviceLink.setTextColor(parseHex(deviceLinkState == DeviceLayoutPolicy.LinkState.CONNECTED
                ? palette.ok() : deviceLinkState == DeviceLayoutPolicy.LinkState.ERROR
                ? palette.error() : palette.ink()));
    }

    private AnswerOutcome.Result currentAnswerOutcome() {
        if (snapshot == null || latestRequestedPanes.isEmpty()) return AnswerOutcome.Result.NONE;
        List<String> states = new ArrayList<>();
        for (String pane : latestRequestedPanes) {
            JSONObject work = answerOf(snapshot, pane);
            String id = work == null ? "" : work.optString("id");
            if (id.isEmpty() || !id.equals(latestRequestIds.get(pane))) {
                return AnswerOutcome.Result.NONE;
            }
            states.add(work.optString("state"));
        }
        return AnswerOutcome.terminal(states);
    }

    /** Cable-out banner sits under the masthead. The device band owns the link state. */
    private void setupLinkBanner() {
        ViewGroup root = (ViewGroup) header.getParent();
        if (root == null) return;
        int afterHeader = root.indexOfChild(header) + 1;
        cableBanner = new LinearLayout(this);
        cableBanner.setOrientation(LinearLayout.VERTICAL);
        cableBanner.setPadding(dp(12), dp(8), dp(12), dp(8));
        cableBanner.setVisibility(View.GONE);
        cableBanner.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        cableBannerTitle = newspaperText("", 16, true, false);
        cableBannerBody = newspaperText(LinkBanner.BODY, 13, false, false);
        // TalkBack reads the banner once, from its description, not each line again.
        cableBannerTitle.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        cableBannerBody.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        cableBanner.addView(cableBannerTitle);
        cableBanner.addView(cableBannerBody);
        root.addView(cableBanner, afterHeader, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
    }

    private void renderLinkBanner(boolean linkConnected, boolean computerWorkVisible) {
        renderDeviceBand(linkConnected);
        if (cableBanner == null) return;
        String noun = ComputerWords.current();
        boolean banner = !coverMode && LinkBanner.showBanner(cableConnected, computerWorkVisible);
        if (banner) {
            cableBanner.setVisibility(View.VISIBLE);
            // Inverted ink, like the paused chip: a planned pull is a pause, not an error.
            int ink = parseHex(palette.ink());
            int paper = parseHex(palette.paper());
            cableBanner.setBackgroundColor(ink);
            setIfChanged(cableBannerTitle, LinkBanner.title(noun));
            cableBannerTitle.setTextColor(paper);
            cableBannerBody.setTextColor(paper);
            String description = LinkBanner.description(noun);
            if (!TextUtils.equals(cableBanner.getContentDescription(), description)) {
                cableBanner.setContentDescription(description);
            }
        } else {
            cableBanner.setVisibility(View.GONE);
            // Cleared so the next pull is announced again.
            cableBanner.setContentDescription(null);
        }
    }

    /** Phone heat: listens only while the app is in front; Android calls back on change. */
    private void startHeatMeter() {
        if (heatMeter == null) return;
        PowerManager power = getSystemService(PowerManager.class);
        if (power == null) {
            showHeat(-1);
            return;
        }
        int current = -1;
        try {
            current = power.getCurrentThermalStatus();
        } catch (RuntimeException ignored) {
            // No reading: the meter stays hidden.
        }
        showHeat(current);
        if (heatRegistered) return;
        try {
            if (heatListener == null) {
                // A callback queued just before onPause() must not touch the view afterwards.
                heatListener = status -> {
                    if (heatRegistered) showHeat(status);
                };
            }
            power.addThermalStatusListener(getMainExecutor(), heatListener);
            heatRegistered = true;
        } catch (RuntimeException ignored) {
            // No change callbacks on this device: the reading above refreshes on resume.
        }
    }

    private void stopHeatMeter() {
        if (!heatRegistered) return;
        heatRegistered = false;
        PowerManager power = getSystemService(PowerManager.class);
        if (power == null || heatListener == null) return;
        try {
            power.removeThermalStatusListener(heatListener);
        } catch (RuntimeException ignored) {
            // Already gone.
        }
    }

    /** Green while cool, ink while warm, red while hot; hidden for an unknown status. */
    private void showHeat(int status) {
        heatStatus = status;
        if (heatMeter == null) return;
        if (!HeatMeter.known(status)) {
            heatMeter.setVisibility(View.GONE);
            return;
        }
        boolean compactHeat = coverMode || compactLayout;
        heatMeter.setTypeface(typography.interSemibold);
        heatMeter.setTextSize(TypedValue.COMPLEX_UNIT_SP,
                compactHeat ? HeatMeter.TEXT_SP_COMPACT : HeatMeter.TEXT_SP);
        setIfChanged(heatMeter, HeatMeter.label(status, compactHeat));
        heatMeter.setTextColor(parseHex(palette.colorForTone(HeatMeter.tone(status))));
        heatMeter.setContentDescription(HeatMeter.description(status));
        heatMeter.setVisibility(View.VISIBLE);
    }

    private void showBattery(Intent battery) {
        if (batteryNotice == null) return;
        typography.body(batteryNotice, typography.bodySp());
        boolean low = battery != null && BatteryNotice.show(
                battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1),
                battery.getIntExtra(BatteryManager.EXTRA_SCALE, 0),
                battery.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0);
        batteryNotice.setVisibility(low ? View.VISIBLE : View.GONE);
        setIfChanged(batteryNotice, low ? getString(R.string.battery_low) : "");
    }

    private String labMode() {
        return coverMode ? DesignLab.coverMode(uiSettings.designLab()) : uiSettings.designLab();
    }

    /** Adds the Design lab card above the lanes when the experimental setting is on. */
    private void addLabView() {
        if (DesignLab.OFF.equals(labMode())) {
            handler.removeCallbacks(labTicker);
            return;
        }
        if (labView == null) {
            labView = new TextView(this);
            labView.setTypeface(typography.jetbrainsMonoMedium);
            // dp: the frame is a fixed-width drawing (hidden from TalkBack); it must not wrap
            // at large font scales. Width in columns is measured from the view below.
            labView.setTextSize(TypedValue.COMPLEX_UNIT_DIP, 14);
            labView.setHorizontallyScrolling(true);
            labView.setIncludeFontPadding(false);
            labView.setLineSpacing(0f, 1.15f);
            labView.setPadding(dp(8), dp(8), dp(8), dp(8));
            labView.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        }
        if (labView.getParent() instanceof ViewGroup) {
            ((ViewGroup) labView.getParent()).removeView(labView);
        }
        labView.setBackground(panelDrawable(palette.stroke()));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.bottomMargin = dp(LaneCardLayout.CARD_GAP_DP);
        answers.addView(labView, params);
        tickLab();
    }

    /** One Design lab frame. Freezes with reduced motion; stops when off or in the background. */
    private void tickLab() {
        handler.removeCallbacks(labTicker);
        String mode = labMode();
        if (labView == null || DesignLab.OFF.equals(mode) || !resumed
                || labView.getParent() == null) return;
        if (!reduceMotionEnabled) labTick++;
        int width = labColumns();
        String frame;
        if (DesignLab.BELTS.equals(mode)) {
            List<DesignLab.Lane> belts = new ArrayList<>();
            if (tonightLanes != null) {
                for (NewspaperSummary.Lane lane : tonightLanes) {
                    if (!lane.included) continue;
                    belts.add(new DesignLab.Lane(lane.label, lane.words,
                            DesignLab.beltFor(lane.state)));
                }
            }
            frame = DesignLab.belts(labTick, belts, width);
        } else {
            frame = DesignLab.schematic(labTick,
                    DesignLab.link(cableConnected, hasVisiblePcWork()),
                    ComputerWords.title(ComputerWords.current()), coverMode ? "Phone" : "This phone", width);
        }
        labView.setTextColor(themeColor(R.color.newspaper_ink));
        setIfChanged(labView, frame);
        // With reduced motion the frame only follows state changes, about once a second.
        handler.postDelayed(labTicker, reduceMotionEnabled ? 1000 : DesignLab.TICK_MS);
    }

    /** Columns of monospace text that fit the card; 40 until the view is measured. */
    private int labColumns() {
        int inner = labView.getWidth() - labView.getPaddingLeft() - labView.getPaddingRight();
        float cell = labView.getPaint().measureText("M");
        if (inner <= 0 || cell <= 0) return 40;
        return (int) Math.floor(inner / cell);
    }

    private boolean hasVisiblePcWork() {
        for (String pane : paneOrder) {
            if (!PaneKeys.pc(pane)) continue;
            PaneViews article = paneViews.get(pane);
            if (open(answerOf(snapshot, pane)) || article != null
                    && latestRequestedPanes.contains(pane)
                    && isPausedDateline(article)) return true;
        }
        return false;
    }

    private boolean isPausedDateline(PaneViews article) {
        return pcWords(R.string.gpu_paused).contentEquals(article.state.getText());
    }

    private Connection pcConnection(JSONObject gpu) {
        if (!reachable || gpu == null) return Connection.UNKNOWN;
        if (Boolean.FALSE.equals(cableConnected)) return Connection.USB_DISCONNECTED;
        JSONObject link = gpu.optJSONObject("link");
        if (link != null && link.optJSONObject("pending") != null) return Connection.PAIRING;
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        long now = SystemClock.elapsedRealtime();
        boolean live = pc != null && pc.optBoolean("live");
        boolean readyGrace = PcHeartbeat.readyGrace(pc != null, lastGoodPcAtMs,
                now, LINK_STATUS_HOLD_MS);
        if (live && gpu.optBoolean("ready") || readyGrace) return Connection.CONNECTED;
        if (live || PcHeartbeat.liveGrace(pc != null, lastPcLiveAtMs,
                now, LINK_STATUS_HOLD_MS)) {
            return Connection.PREPARING;
        }
        return Connection.DISCONNECTED;
    }

    private String infoPcStatus(Connection connection) {
        switch (connection) {
            case USB_DISCONNECTED: return getString(R.string.info_usb_disconnected);
            case PAIRING: return getString(R.string.info_pairing_requested);
            case CONNECTED: return getString(R.string.info_pc_connected);
            case PREPARING: return getString(R.string.info_pc_preparing);
            case DISCONNECTED: return getString(R.string.info_pc_disconnected);
            default: return getString(R.string.info_unknown);
        }
    }

    private String infoPairingStatus(SettingsPcState.Pairing pairing) {
        switch (pairing) {
            case REQUESTED: return getString(R.string.info_pairing_requested);
            case CLOSED: return getString(R.string.info_pairing_closed);
            case SAVED: return pcWords(R.string.info_pairing_saved);
            case NONE: return pcWords(R.string.info_pairing_none);
            default: return getString(R.string.info_unknown);
        }
    }

    private void updateInfoPcRows(Dialog dialog, JSONObject gpu, Connection connection) {
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        SettingsPcState rows = SettingsPcState.from(link != null, pc != null,
                link != null && link.optJSONObject("pending") != null,
                link != null && "closed".equals(link.optString("enrol")),
                pcLabel(gpu), pcFingerprint(pc), connection, reachable);
        String pcText = pc == null ? pcWords(R.string.info_no_pc)
                : rows.label.isEmpty() ? pcWords(R.string.pc) : rows.label;
        String idText = pc == null ? pcWords(R.string.info_no_pc)
                : rows.fingerprint.isEmpty() ? getString(R.string.info_pc_id_unavailable)
                : rows.fingerprint;
        // One main-thread pass keeps the Settings rows on the same snapshot.
        // Clear a departed PC's status before showing "No PC selected".
        if (pc == null) setIfChanged(dialog.findViewById(R.id.info_pc_status),
                infoPcStatus(rows.connection));
        setIfChanged(dialog.findViewById(R.id.info_pc), pcText);
        setIfChanged(dialog.findViewById(R.id.info_pc_id), idText);
        if (pc != null) setIfChanged(dialog.findViewById(R.id.info_pc_status),
                infoPcStatus(rows.connection));
        setIfChanged(dialog.findViewById(R.id.info_pairing), infoPairingStatus(rows.pairing));
        applyTone(dialog.findViewById(R.id.info_pc_status));
        applyTone(dialog.findViewById(R.id.info_pairing));
        View forgetPc = dialog.findViewById(R.id.info_forget_pc);
        forgetPc.setVisibility(rows.canForget ? View.VISIBLE : View.GONE);
        forgetPc.setEnabled(rows.canForget && !acting);
    }

    /** Keep the plain timing text for History and redraw the aligned two-column list. */
    private void setTonightTiming(String timing) {
        setTonightTiming(timing, null);
    }

    private void setTonightTiming(String timing, List<NewspaperSummary.Lane> lanes) {
        if (timing.contentEquals(tonightTiming.getText()) && tonightRows.getChildCount() > 0
                && lanes == tonightLanes) {
            return;
        }
        tonightLanes = lanes;
        tonightTiming.setText(timing);
        fillTonightRows(tonightRows, timing, lanes);
    }

    /** Label column on the left, tabular figures right-aligned on a shared edge. */
    private void fillTonightRows(LinearLayout container, String timing,
                                 List<NewspaperSummary.Lane> lanes) {
        container.removeAllViews();
        int maxWords = RaceLine.maxWords(lanes);
        if (tonightLeader != null && container == tonightRows) {
            // The leader belongs to the live TONIGHT card only. While a question runs its line
            // keeps its space (INVISIBLE), so the answers below do not jump when it appears.
            String leader = lanes == null ? "" : RaceLine.leader(lanes);
            setIfChanged(tonightLeader, leader.isEmpty() ? " " : leader);
            tonightLeader.setVisibility(!leader.isEmpty() ? View.VISIBLE
                    : lanes == null ? View.GONE : View.INVISIBLE);
            tonightLeader.setTextColor(parseHex(palette.ok()));
        }
        List<TonightRows.Row> rows = TonightRows.parse(timing);
        List<NewspaperSummary.Lane> rowLanes = TonightRows.matchingLanes(rows, lanes);
        for (int rowIndex = 0; rowIndex < rows.size(); rowIndex++) {
            TonightRows.Row row = rows.get(rowIndex);
            if (row.note()) {
                TextView note = newspaperText(row.label, 12, false, false);
                typography.tabular(note);
                note.setPadding(0, dp(2), 0, dp(2));
                applyTone(note);
                container.addView(note, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));
                continue;
            }
            LinearLayout line = new LinearLayout(this);
            line.setOrientation(LinearLayout.HORIZONTAL);
            line.setGravity(Gravity.BOTTOM);
            line.setPadding(0, dp(3), 0, dp(3));
            TextView label = newspaperText(row.label, 14, false, false);
            label.setSingleLine(false);
            TextView value = newspaperText(row.value, 14, true, false);
            typography.tabular(value);
            value.setGravity(Gravity.END);
            value.setMinWidth(dp(56));
            NewspaperSummary.Lane lane = rowLanes.get(rowIndex);
            int color = parseHex(palette.colorForTone(TonightRows.tone(row, lane)));
            label.setTextColor(color);
            value.setTextColor(color);
            line.addView(label, new LinearLayout.LayoutParams(0,
                    LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
            LinearLayout.LayoutParams valueParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            valueParams.leftMargin = dp(12);
            line.addView(value, valueParams);
            container.addView(line, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
            if (lane != null && lane.included) {
                line.setContentDescription(RaceLine.rowDescription(row.label, row.value, lane.words));
                // One TalkBack stop per row that reads the description, not label and time apart.
                line.setScreenReaderFocusable(true);
                label.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                value.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            }
            if (lane != null && lane.included && maxWords > 0) {
                // Words so far against the longest lane, labelled in words so the bar is never
                // read as the time printed on the row above.
                TextView bar = new TextView(this);
                bar.setTypeface(typography.jetbrainsMonoMedium);
                // dp, not sp: the bar is decorative (hidden from TalkBack) and must stay one
                // line at large font scales; the row above it carries the words.
                bar.setTextSize(TypedValue.COMPLEX_UNIT_DIP, 11);
                bar.setIncludeFontPadding(false);
                bar.setMaxLines(1);
                bar.setPadding(0, 0, 0, dp(2));
                bar.setText(RaceLine.barWithWords(lane.words, maxWords, RaceLine.CELLS));
                bar.setTextColor(color);
                bar.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                container.addView(bar, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT));
            }
        }
    }

    private void setSummaryReport(String report) {
        paintSummaryReport(summaryText, report);
        paintSummaryReport(fullSummaryText, report);
    }

    private void paintSummaryReport(TextView view, String report) {
        if (view == null) return;
        String text = report == null ? "" : report;
        int ink = themeColor(R.color.newspaper_ink);
        int error = parseHex(palette.error());
        int bodySp = typography.bodySp();
        if (!SummaryPaintPolicy.needsPaint(summaryPaints.get(view), text, ink, error, bodySp)) return;
        typography.body(view, bodySp);
        SpannableStringBuilder styled = new SpannableStringBuilder(text);
        if (styled.length() > 0) {
            styled.setSpan(new ForegroundColorSpan(ink), 0, styled.length(),
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        for (ErrorCopy.Range range : ErrorCopy.lineRanges(text)) {
            if (!range.error) continue;
            styled.setSpan(new ForegroundColorSpan(error), range.start, range.end,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        view.setTextColor(ink);
        view.setText(styled);
        summaryPaints.put(view, new SummaryPaintPolicy.Paint(text, ink, error, bodySp));
    }

    /** The pinned preview can clip a five-model report; this page shows every line. */
    private void showSummaryPage() {
        if (summaryDialog != null && summaryDialog.isShowing()) return;
        if (isFinishing() || isDestroyed()) return;
        Dialog dialog = new Dialog(this, R.style.NewspaperDialogTheme);
        summaryDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (summaryDialog == dialog) {
                summaryDialog = null;
                fullSummaryText = null;
                syncWorkingAnimation();
            }
        });
        LinearLayout root = pageRoot();
        root.addView(pageBar(getString(R.string.summary_title), getString(R.string.close),
                view -> dialog.dismiss()));
        ScrollView scroll = new ScrollView(this);
        fullSummaryText = newspaperText("", typography.bodySp(), false, true);
        fullSummaryText.setTextIsSelectable(true);
        fullSummaryText.setPadding(0, dp(12), 0, dp(16));
        scroll.addView(fullSummaryText);
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        paintSummaryReport(fullSummaryText, summaryText == null ? "" : summaryText.getText().toString());
        showFullPage(dialog, root);
        applyPaletteToDialog(dialog);
        syncWorkingAnimation();
    }

    /** A string resource with "PC" replaced by the paired computer's noun (MacBook, Mac or PC). */
    private String pcWords(int id) {
        return ComputerWords.apply(getString(id));
    }

    private String pcWords(int id, Object... args) {
        String template = ComputerWords.apply(getString(id));
        return args.length == 0 ? template : String.format(template, args);
    }

    /** Remember a fixed label that names the computer, so a new pairing can rename it. */
    private void pcLabelled(TextView view, String original) {
        if (view == null || original == null || original.indexOf("PC") < 0) return;
        pcLabelledViews.put(view, original);
        view.setText(ComputerWords.apply(original));
    }

    /** Static XML labels that name the computer; dynamic views are re-set on every render. */
    private void pcLabelStatic(View root, int[][] idsAndStrings) {
        if (root == null) return;
        for (int[] pair : idsAndStrings) {
            View view = root.findViewById(pair[0]);
            if (view instanceof TextView) pcLabelled((TextView) view, getString(pair[1]));
        }
    }

    /**
     * Follow the paired computer. A snapshot that confirms no PC is paired (and none pending)
     * resets the noun to the neutral "computer"; a transient connection loss keeps it.
     */
    private void observeComputer(String label, JSONObject link, JSONObject pc) {
        boolean changed = link != null && pc == null && link.optJSONObject("pending") == null
                ? ComputerWords.set(ComputerWords.COMPUTER) : ComputerWords.observe(label);
        if (!changed) return;
        getPreferences(MODE_PRIVATE).edit().putString("computer_noun", ComputerWords.current()).apply();
        for (Map.Entry<TextView, String> entry : pcLabelledViews.entrySet()) {
            entry.getKey().setText(ComputerWords.apply(entry.getValue()));
        }
    }

    /** The model recorded on a lane's current answer; "" when there is no answer or model. */
    private static String answeredModel(JSONObject lane) {
        JSONObject answer = lane == null ? null : lane.optJSONObject("answer");
        return answer == null || answer.isNull("model") ? "" : answer.optString("model", "").trim();
    }

    /** A computer's display label; JSON null or a missing object is "" (optString would say "null"). */
    private static String computerLabel(JSONObject computer) {
        return computer == null || computer.isNull("label") ? "" : computer.optString("label", "").trim();
    }

    private static void setIfChanged(TextView view, String text) {
        if (!text.contentEquals(view.getText())) view.setText(text);
    }

    private void setLaneState(TextView stateView, View card, String text) {
        PaneViews matchingArticle = null;
        for (PaneViews article : paneViews.values()) {
            if (article.state == stateView) {
                matchingArticle = article;
                break;
            }
        }
        // Hide the raw live label before changing it; TalkBack should hear only "Working".
        if (matchingArticle != null) {
            if (WorkingIndicator.working(text)) {
                if (stateView.getVisibility() != View.GONE) stateView.setVisibility(View.GONE);
            } else if (stateView.getVisibility() != View.VISIBLE) {
                matchingArticle.workingRow.setVisibility(View.GONE);
                stateView.setVisibility(View.VISIBLE);
            }
        }
        setIfChanged(stateView, text);
        applyTone(stateView);
        if (card != null) applyCardStroke(card, UiPalette.tone(text));
        if (matchingArticle != null) updateWorking(matchingArticle);
        syncWorkingAnimation();
    }

    private TextView workingLine(TextView stateView) {
        TextView view = new TextView(this);
        typography.state(view); // the state slot (S5 face, tabular numbers), same size as above
        view.setIncludeFontPadding(stateView.getIncludeFontPadding());
        view.setPadding(stateView.getPaddingLeft(), stateView.getPaddingTop(),
                stateView.getPaddingRight(), stateView.getPaddingBottom());
        view.setTextColor(themeColor(R.color.newspaper_ink));
        // A steady live region says "Working" once; answer growth does not repeat it.
        view.setContentDescription(WorkingIndicator.spoken(WorkingIndicator.STREAMING, 0));
        view.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        return view;
    }

    private TextView workingCountLine() {
        TextView view = new TextView(this);
        typography.state(view);
        view.setTextColor(themeColor(R.color.newspaper_ink));
        view.setSingleLine(true);
        view.setEllipsize(TextUtils.TruncateAt.END);
        view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        return view;
    }

    /** Color-only span: changing its alpha needs a draw, never a new text layout. */
    private static final class AlphaColorSpan extends CharacterStyle implements UpdateAppearance {
        private final int rgb;
        private int alpha = 255;

        AlphaColorSpan(int color) {
            rgb = color & 0x00FFFFFF;
        }

        boolean setAlpha(float amount) {
            int next = Math.round(255f * amount);
            if (alpha == next) return false;
            alpha = next;
            return true;
        }

        @Override public void updateDrawState(TextPaint paint) {
            paint.setColor(rgb | (alpha << 24));
        }
    }

    private static final class WorkingSpans {
        String line = "";
        int green, ink;
        AlphaColorSpan dot;
        final AlphaColorSpan[] dots = new AlphaColorSpan[WorkingIndicator.DOT_COUNT];
    }

    private void setWorkingText(TextView view, WorkingSpans spans, String line) {
        int green = parseHex(palette.ok());
        int ink = themeColor(R.color.newspaper_ink);
        if (line.equals(spans.line) && green == spans.green && ink == spans.ink) return;
        SpannableString styled = new SpannableString(line);
        spans.dot = new AlphaColorSpan(green);
        styled.setSpan(spans.dot, 0, 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        int firstDot = line.indexOf("...");
        for (int dot = 0; dot < WorkingIndicator.DOT_COUNT; dot++) {
            spans.dots[dot] = new AlphaColorSpan(ink);
            styled.setSpan(spans.dots[dot], firstDot + dot, firstDot + dot + 1,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        view.setTextColor(ink);
        view.setText(styled, TextView.BufferType.SPANNABLE);
        spans.line = line;
        spans.green = green;
        spans.ink = ink;
    }

    /** Shows or hides one lane's working line; only its dot is green. */
    private void updateWorking(PaneViews article) {
        if (article == null || article.working == null) return;
        TextView view = article.working;
        if (!WorkingIndicator.working(article.state.getText())) {
            if (article.workingRow.getVisibility() != View.GONE) {
                article.workingRow.setVisibility(View.GONE);
            }
            if (article.state.getVisibility() != View.VISIBLE) article.state.setVisibility(View.VISIBLE);
            return;
        }
        String line = WorkingIndicator.line(article.state.getText());
        setWorkingText(view, article.workingSpans, line);
        setIfChanged(article.workingCount, WorkingIndicator.count(article.words));
        if (article.state.getVisibility() != View.GONE) article.state.setVisibility(View.GONE);
        if (article.workingRow.getVisibility() != View.VISIBLE) {
            article.workingRow.setVisibility(View.VISIBLE);
        }
    }

    private void drawWorkingFrame(TextView view, WorkingSpans spans, float frame, boolean still) {
        if (view == null || spans.dot == null) return;
        boolean changed = spans.dot.setAlpha(WorkingIndicator.dotAlpha(frame, still));
        for (int dot = 0; dot < WorkingIndicator.DOT_COUNT; dot++) {
            changed |= spans.dots[dot].setAlpha(
                    WorkingIndicator.trailingAlpha(frame, dot, still));
        }
        if (changed) view.invalidate();
    }

    private void drawWorkingFrame(PaneViews article, float frame, boolean still) {
        drawWorkingFrame(article.working, article.workingSpans, frame, still);
    }

    private void stopWorkingAnimation() {
        if (workingAnimator != null && workingAnimator.isStarted()) workingAnimator.cancel();
        for (int i = 0; i < animatedWorking.size(); i++) {
            drawWorkingFrame(animatedWorking.get(i), 0f, true);
        }
        drawWorkingFrame(expandedState, expandedWorkingSpans, 0f, true);
        animatedWorking.clear();
        expandedWorkingAnimated = false;
    }

    /** Only visible live lines receive frames; scrolling and layout changes resync the list. */
    private void syncWorkingAnimation() {
        boolean articleOpen = articleDialog != null && articleDialog.isShowing();
        boolean summaryOpen = summaryDialog != null && summaryDialog.isShowing();
        boolean inViewport = !articleOpen && !summaryOpen
                && resultsScroll != null && resultsScroll.isShown()
                && resultsScroll.hasWindowFocus()
                && resultsScroll.getGlobalVisibleRect(workingViewport);
        boolean motionOff = readReducedMotion();
        boolean animatorsEnabled = ValueAnimator.areAnimatorsEnabled();
        animatedWorking.clear();
        for (PaneViews article : paneViews.values()) {
            boolean live = article.workingRow != null
                    && article.workingRow.getVisibility() == View.VISIBLE;
            boolean onScreen = inViewport && live && article.working.isAttachedToWindow()
                    && article.working.isShown()
                    && article.working.getGlobalVisibleRect(workingBounds)
                    && Rect.intersects(workingViewport, workingBounds);
            if (WorkingIndicator.animate(live, onScreen, resumed, motionOff, animatorsEnabled)) {
                animatedWorking.add(article);
            } else if (live) {
                drawWorkingFrame(article, 0f, true);
            }
        }
        boolean expandedLive = articleOpen && !summaryOpen && expandedState != null
                && !expandedWorkingSpans.line.isEmpty();
        boolean expandedOnScreen = expandedLive && expandedState.isAttachedToWindow()
                && expandedState.isShown() && expandedState.hasWindowFocus()
                && expandedState.getGlobalVisibleRect(workingBounds);
        expandedWorkingAnimated = WorkingIndicator.animate(expandedLive, expandedOnScreen,
                resumed, motionOff, animatorsEnabled);
        if (expandedLive && !expandedWorkingAnimated) {
            drawWorkingFrame(expandedState, expandedWorkingSpans, 0f, true);
        }
        if (animatedWorking.isEmpty() && !expandedWorkingAnimated) {
            stopWorkingAnimation();
            return;
        }
        if (workingAnimator == null) {
            workingAnimator = ValueAnimator.ofFloat(0f, 1f);
            workingAnimator.setDuration(WorkingIndicator.CYCLE_MS);
            workingAnimator.setRepeatCount(ValueAnimator.INFINITE);
            workingAnimator.setInterpolator(new LinearInterpolator());
            workingAnimator.addUpdateListener(animation -> {
                if (!ValueAnimator.areAnimatorsEnabled()) {
                    syncWorkingAnimation();
                    return;
                }
                float frame = animation.getAnimatedFraction();
                for (int i = 0; i < animatedWorking.size(); i++) {
                    drawWorkingFrame(animatedWorking.get(i), frame, false);
                }
                if (expandedWorkingAnimated) {
                    drawWorkingFrame(expandedState, expandedWorkingSpans, frame, false);
                }
            });
        }
        float frame = workingAnimator.isRunning() ? workingAnimator.getAnimatedFraction() : 0f;
        for (int i = 0; i < animatedWorking.size(); i++) {
            drawWorkingFrame(animatedWorking.get(i), frame, false);
        }
        if (expandedWorkingAnimated) {
            drawWorkingFrame(expandedState, expandedWorkingSpans, frame, false);
        }
        if (!workingAnimator.isRunning()) workingAnimator.start();
    }

    private void setQuestionHeadline(TextView view, String fullText) {
        if (view == null) return;
        String prefix = getString(R.string.you_asked, "");
        String formatted = QuestionHeadline.formatHeadline(fullText, prefix);
        if (formatted.contentEquals(view.getText()) && view.getText() instanceof Spanned) {
            applyQuestionLayout(view);
            return;
        }
        SpannableStringBuilder styled = new SpannableStringBuilder(formatted);
        int prefixEnd = QuestionHeadline.prefixLength(formatted, prefix);
        if (prefixEnd > 0) {
            styled.setSpan(new TypefaceSpan(typography.subheadSemibold), 0, prefixEnd,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            styled.setSpan(new AbsoluteSizeSpan(typography.labelSp(), true),
                    0, prefixEnd, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        view.setTextColor(themeColor(R.color.newspaper_ink));
        view.setText(styled);
        applyQuestionLayout(view);
        keepCoverHeadlineOnScreen();
    }

    private int questionSizeSp() {
        return landscapeLayout ? TypeConfig.header().sizeSp : QuestionHeadline.baseSp(coverMode);
    }

    private int questionMinLines() {
        return landscapeLayout ? 1 : QuestionHeadline.minLines(coverMode);
    }

    private int questionMaxLines() {
        return landscapeLayout ? 2 : QuestionHeadline.maxLines(coverMode);
    }

    /** Bigger H5/S5-scale question type: wrap, 1.25 leading, shrink so it never clips. */
    private void applyQuestionLayout(TextView view) {
        if (view == null) return;
        view.setAutoSizeTextTypeWithDefaults(TextView.AUTO_SIZE_TEXT_TYPE_NONE);
        view.setScaleX(1f);
        view.setScaleY(1f);
        // A leftover maxHeight of a few pixels will crush wrap_content; lift any cap first.
        view.setMaxHeight(Integer.MAX_VALUE);
        int sizeSp = questionSizeSp();
        applyQuestionType(view, sizeSp);
        view.setIncludeFontPadding(true);
        view.setSingleLine(false);
        view.setMinLines(questionMinLines());
        view.setBreakStrategy(Layout.BREAK_STRATEGY_HIGH_QUALITY);
        view.setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NONE);
        view.setEllipsize(null);
        int maxLines = questionMaxLines();
        view.setMaxLines(maxLines);
        applyQuestionMinHeight(view, sizeSp);
        ViewGroup.LayoutParams params = view.getLayoutParams();
        if (params != null) {
            params.width = ViewGroup.LayoutParams.MATCH_PARENT;
            params.height = ViewGroup.LayoutParams.WRAP_CONTENT;
            view.setLayoutParams(params);
        }
        view.requestLayout();
        view.post(() -> shrinkQuestionToFit(view));
    }

    /**
     * Size with StaticLayout, never measure() the live view (that can leave a
     * hairline measured height in the next layout pass).
     */
    private void shrinkQuestionToFit(TextView view) {
        if (view == null || view.getWidth() <= 0) return;
        view.setAutoSizeTextTypeWithDefaults(TextView.AUTO_SIZE_TEXT_TYPE_NONE);
        view.setMaxHeight(Integer.MAX_VALUE);
        int maxLines = questionMaxLines();
        int floor = QuestionHeadline.floorSp(coverMode);
        int sizeSp = questionSizeSp();
        int width = Math.max(1, view.getWidth() - view.getPaddingLeft() - view.getPaddingRight());
        CharSequence text = view.getText();
        if (text == null) text = "";
        while (true) {
            applyQuestionType(view, sizeSp);
            int lines = questionLineCount(view, text, width);
            int next = QuestionHeadline.shrinkSp(sizeSp, floor, lines, maxLines);
            if (next == sizeSp) break;
            sizeSp = next;
        }
        applyQuestionType(view, sizeSp);
        int lines = Math.max(1, questionLineCount(view, text, width));
        int fittedLines = sizeSp == floor ? Math.max(maxLines, lines) : maxLines;
        view.setEllipsize(null);
        view.setMinLines(questionMinLines());
        view.setMaxLines(fittedLines);
        applyQuestionMinHeight(view, sizeSp);
        view.requestLayout();
    }

    private void applyQuestionType(TextView view, int sizeSp) {
        typography.headline(view, sizeSp);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp);
        typography.applyLineHeight(view, sizeSp, QuestionHeadline.LEADING);
    }

    private void applyQuestionMinHeight(TextView view, int sizeSp) {
        int line = Math.max(dp(20), Math.max(view.getLineHeight(),
                Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP,
                        sizeSp * QuestionHeadline.LEADING, getResources().getDisplayMetrics()))));
        int min = Math.max(dp(landscapeLayout ? 28 : 48), line * questionMinLines());
        view.setMinHeight(min);
        view.setMinimumHeight(min);
        view.setMaxHeight(Integer.MAX_VALUE);
    }

    private static int questionLineCount(TextView view, CharSequence text, int width) {
        if (text.length() == 0 || width <= 0) return 1;
        android.text.StaticLayout layout = android.text.StaticLayout.Builder
                .obtain(text, 0, text.length(), view.getPaint(), width)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .setIncludePad(true)
                .setLineSpacing(view.getLineSpacingExtra(), view.getLineSpacingMultiplier())
                .setBreakStrategy(Layout.BREAK_STRATEGY_HIGH_QUALITY)
                .setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NONE)
                .build();
        return Math.max(1, layout.getLineCount());
    }

    private void keepCoverHeadlineOnScreen() {
        if (!coverMode || resultsScroll == null || question == null) return;
        if (question.getVisibility() != View.VISIBLE || TextUtils.isEmpty(question.getText())) return;
        resultsScroll.post(() -> {
            int top = Math.max(0, yInScrollContent(question));
            int next = CoverScreenPolicy.keepHeadlineVisible(
                    resultsScroll.getScrollY(), top, true, true);
            if (next != resultsScroll.getScrollY()) resultsScroll.scrollTo(0, next);
            setHeaderCollapse(resultsScroll.getScrollY());
        });
    }

    private void syncErrorVisibility() {
        if (error == null) return;
        error.setVisibility(TextUtils.isEmpty(error.getText()) ? View.GONE : View.VISIBLE);
    }

    private void setMainStatus(String text) {
        setIfChanged(status, text);
        applyTone(status);
        if (expandedStatus != null) {
            setIfChanged(expandedStatus, text);
            applyTone(expandedStatus);
        }
    }

    private void updateCompactLaneStatus() {
        if (compactLaneStatus != null) {
            Map<String, String> states = new HashMap<>();
            for (String pane : paneOrder) {
                PaneViews article = paneViews.get(pane);
                if (article != null) states.put(pane, article.state.getText().toString());
            }
            String notAsked = getString(R.string.not_asked_this_time);
            String checking = getString(R.string.checking);
            String phone = CompactHeaderStatus.selectedState(
                    paneOrder, states, false, notAsked, checking);
            String pc = CompactHeaderStatus.selectedState(
                    paneOrder, states, true, notAsked, checking);
            setIfChanged(compactLaneStatus, CompactHeaderStatus.line(
                    getString(R.string.phone_heading), phone,
                    pcWords(R.string.gpu_heading), pc,
                    pcWords(R.string.gpu_paused)));
        }
        refreshCover();
    }

    private static void setPlainAnswer(TextView view, String text) {
        // The next model answer must be styled even if its raw text matches an older one.
        view.setTag(null);
        setIfChanged(view, text);
    }

    private void setMarkdownAnswer(TextView view, String raw) {
        // Polling often returns the same partial answer. Avoid resetting spans and selection.
        if (raw.equals(view.getTag())) return;
        view.setText(AnswerMarkdown.render(raw, view.getPaint(), typography));
        view.setTag(raw);
    }

    private void restoreFailedDraftIfUntouched() {
        if (clearedDraftRevision < 0 || draftRevision != clearedDraftRevision
                || prompt.length() != 0 || !clearedDraft.equals(latestQuestion)) return;
        for (String pane : paneNames(snapshot)) {
            if (failedForQuestion(pane, answerOf(snapshot, pane))) {
                prompt.setText(clearedDraft);
                prompt.setSelection(prompt.length());
                clearedDraftRevision = -1;
                clearedDraft = "";
                return;
            }
        }
    }

    /**
     * The computer's main worker is talking to the phone (main_live, not just an extra lane) and
     * has a model up: state "ready" or "busy" answering. Copying or loading a model is warmup,
     * not a stall. ("gpu.ready" alone is false while busy, so it would hide a mid-answer stall.)
     */
    private static boolean gpuLaneReady(JSONObject data) {
        JSONObject gpu = data == null ? null : data.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        return pc != null && GpuLaneReadiness.ready(pc.optBoolean("main_live", pc.optBoolean("live")),
                pc.isNull("state") ? null : pc.optString("state", null));
    }

    private boolean gpuCanQueue(JSONObject gpu) {
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        return link != null && link.optJSONObject("pc") != null;
    }

    private void updateButtons() {
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        boolean running = anyBlockingOpen();
        boolean waitingForId = awaitingAnswerId();
        boolean canAsk = anyReadyPane();
        send.setVisibility(offline || running ? View.GONE : View.VISIBLE);
        stop.setVisibility(!offline && running ? View.VISIBLE : View.GONE);
        reconnect.setVisibility(offline ? View.VISIBLE : View.GONE);
        send.setEnabled(reachable && !acting && !quitting && !running && !waitingForId
                && !pairingPending && canAsk);
        stop.setEnabled(reachable && !acting && !quitting && running);
        reconnect.setEnabled(offline && !polling && !acting);
        boolean ambiguous = askRecovery.unresolved();
        resetAsk.setVisibility(ambiguous ? View.VISIBLE : View.GONE);
        resetAskCopy.setVisibility(ambiguous ? View.VISIBLE : View.GONE);
        resetAsk.setEnabled(ambiguous && !acting && !quitting);
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        boolean pairingPending = link != null && link.optJSONObject("pending") != null;
        boolean validPairing = pairingPending && !pairingTimedOut
                && rejectedPairingCode.isEmpty() && pairingCode != null
                && PairingPrompt.validCode(pairingCode.getText().toString());
        allow.setEnabled(reachable && !acting && !quitting && validPairing);
        deny.setEnabled(reachable && !acting && !quitting && validPairing);
        reopen.setEnabled(reachable && !acting && !quitting);
        boolean retryable = false;
        boolean retryReady = false;
        for (String pane : paneNames(snapshot)) {
            if (!laneSelection.isOn(paneNames(snapshot), readyPanes(snapshot), pane)) continue;
            JSONObject view = paneOf(snapshot, pane);
            if (!retryablePane(pane, answerOf(snapshot, pane))) continue;
            retryable = true;
            if (PaneKeys.pc(pane) ? !Boolean.FALSE.equals(cableConnected)
                    && ("gpu".equals(pane) ? gpuCanQueue(view)
                    : view != null && view.optBoolean("ready"))
                    : view != null && view.optBoolean("ready")) retryReady = true;
        }
        retry.setVisibility(retryable ? View.VISIBLE : View.GONE);
        retry.setEnabled(reachable && !acting && !quitting && !running && retryReady);
        styleErrorButton(retry, retryable);
        for (Map.Entry<String, Button> entry : laneRetryButtons.entrySet()) {
            Button laneRetry = entry.getValue();
            laneRetry.setEnabled(laneRetry.getVisibility() == View.VISIBLE
                    && RetryControls.laneEnabled(entry.getKey(), cableConnected,
                    Boolean.TRUE.equals(laneRetryReady.get(entry.getKey())),
                    reachable, acting, quitting));
        }
        applyComposerState();
        applyErrorView();
    }

    private boolean failedForQuestion(String pane, JSONObject answer) {
        return answer != null && "failed".equals(answer.optString("state"))
                && !TextUtils.isEmpty(latestQuestion)
                && latestQuestion.equals(answer.optString("question"))
                && latestRequestedPanes.contains(pane)
                && answer.optString("id").equals(latestRequestIds.get(pane));
    }

    private boolean retryablePane(String pane, JSONObject answer) {
        return failedForQuestion(pane, answer) || missingIdExpired(pane);
    }

    private void askModels() {
        // A bare "again" or "retry" would reach the models with no history; send the real question.
        sendQuestion(FollowUpPolicy.resolve(prompt.getText().toString(), lastSubmittedQuestion), false);
    }

    private void retryFailed() {
        // The page-level Retry must use the same safer, ID-bound path for garbage.
        Map<String, Boolean> ready = readyPanes(snapshot);
        for (String pane : laneSelection.selected(paneNames(snapshot), ready)) {
            JSONObject answer = answerOf(snapshot, pane);
            if (Boolean.TRUE.equals(ready.get(pane)) && failedForQuestion(pane, answer)
                    && (laneHealth.garbled(pane, answer.optString("id"))
                    || "garbled".equals(answer.optString("error"))
                    || AnswerGuard.reason(answer.optString("text")) != null)) {
                retryLane(pane, false);
                return;
            }
        }
        sendQuestion(FollowUpPolicy.originalQuestion(latestQuestion, lastSubmittedQuestion), true);
    }

    private boolean sendQuestion(String text, boolean failedOnly) {
        if (snapshot == null || !reachable || acting || quitting || pairingPending
                || awaitingAnswerId()) return false;
        if (text.isEmpty()) {
            error.setText(R.string.enter_question);
            return false;
        }
        if (text.getBytes(StandardCharsets.UTF_8).length > 4096) {
            error.setText(R.string.question_too_long);
            return false;
        }
        if (anyBlockingOpen()) return false;
        List<String> ordered = paneNames(snapshot);
        Map<String, Boolean> ready = readyPanes(snapshot);
        List<String> selected = laneSelection.selected(ordered, ready);
        Map<String, Boolean> eligible = new HashMap<>();
        for (String pane : ordered) {
            eligible.put(pane, selected.contains(pane) && Boolean.TRUE.equals(ready.get(pane))
                    && (!failedOnly
                    || retryablePane(pane, answerOf(snapshot, pane))));
        }
        JSONArray panes = new JSONArray();
        for (String pane : PaneKeys.readyPanes(ordered, eligible)) panes.put(pane);
        if (panes.length() == 0) {
            error.setText(R.string.connect_to_send);
            return false;
        }
        JSONObject body = action("ask");
        try {
            body.put("question", text);
            body.put("panes", panes);
        } catch (JSONException impossible) {
            throw new AssertionError(impossible);
        }
        sendAction(body, text, SystemClock.elapsedRealtime(), failedOnly);
        return true;
    }

    private void addLaneRetryButton(String pane, LinearLayout card) {
        Button button = outlineButton(getString(R.string.lane_retry)); // 0.5dp dark-gray frame
        typography.retry(button);
        button.setPadding(dp(14), 0, dp(14), 0);
        button.setVisibility(View.GONE);
        button.setContentDescription(getString(R.string.lane_retry_description));
        button.setOnClickListener(view -> retryLane(pane, false));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(8);
        card.addView(button, params);
        laneRetryButtons.put(pane, button);
    }

    /** Show Retry on a lane that is stuck, paused, failed, stopped or finished; retry once by itself. */
    private void updateLaneRetry(JSONObject data) {
        long now = SystemClock.elapsedRealtime();
        laneHealth.observeCable(cableConnected, now);
        Map<String, Boolean> ready = readyPanes(data);
        String autoPane = null;
        String autoQuestion = "";
        for (Map.Entry<String, Button> entry : laneRetryButtons.entrySet()) {
            String pane = entry.getKey();
            Button button = entry.getValue();
            JSONObject answer = answerOf(data, pane);
            String id = answer == null ? "" : answer.optString("id");
            boolean tracked = answer != null && !id.isEmpty()
                    && (latestRequestedPanes.isEmpty()
                    || latestRequestedPanes.contains(pane)
                    && id.equals(latestRequestIds.get(pane)));
            if (!tracked) {
                laneHealth.observe(pane, "", "", null, 0, "", false, now);
                laneRetryReady.remove(pane);
                button.setVisibility(View.GONE);
                continue;
            }
            // Send may queue on a paired computer that is still warming, but health and Retry
            // need the lane actually ready, so a warmup is never read as a stall.
            boolean canQueue = Boolean.TRUE.equals(ready.get(pane));
            boolean laneReady = canQueue && (!"gpu".equals(pane) || gpuLaneReady(data));
            laneRetryReady.put(pane, laneReady);
            String question = answer.optString("question");
            LaneHealth.Verdict verdict = laneHealth.observe(pane, id, answer.optString("state"),
                    answer.optString("error"), answer.optLong("bytes", answer.optString("text").length()),
                    answer.optString("text"), question, laneReady, now);
            if (!verdict.retryVisible) {
                button.setVisibility(View.GONE);
                continue;
            }
            button.setVisibility(View.VISIBLE);
            setIfChanged(button, getString(verdict.garbled ? R.string.answer_garbled
                    : verdict.status == LaneHealth.Status.STUCK
                    ? R.string.lane_retry_stuck : R.string.lane_retry));
            styleLaneRetry(button, verdict);
            boolean enabled = RetryControls.laneEnabled(pane, cableConnected, laneReady,
                    reachable, acting, quitting);
            button.setEnabled(enabled);
            if (verdict.autoRetryDue && enabled && autoPane == null
                    && !FollowUpPolicy.bareFollowUp(FollowUpPolicy.originalQuestion(
                    question, lastSubmittedQuestion))) {
                autoPane = pane;
                autoQuestion = question;
            }
        }
        if (autoPane != null && !acting && visible) {
            laneHealth.markAutoRetried(autoPane, autoQuestion);
            retryLane(autoPane, true);
        }
    }

    /**
     * Rerun one lane's current question. The phone refuses a Retry whose expected answer ID is no
     * longer the lane's latest, so a double tap or a replayed request cannot cancel a fresh answer.
     */
    private void retryLane(String pane, boolean automatic) {
        if (snapshot == null || !reachable || acting || quitting) return;
        JSONObject answer = answerOf(snapshot, pane);
        if (answer == null || answer.optString("id").isEmpty()) return;
        String oldId = answer.optString("id");
        String question = FollowUpPolicy.originalQuestion(
                answer.optString("question"), lastSubmittedQuestion);
        if (automatic && FollowUpPolicy.bareFollowUp(question)) return;
        JSONObject body = action("retry");
        try {
            body.put("pane", pane);
            body.put("id", oldId);
            if (laneHealth.garbled(pane, oldId) || "garbled".equals(answer.optString("error"))
                    || AnswerGuard.reason(answer.optString("text")) != null) body.put("safe", 1);
        } catch (JSONException impossible) {
            throw new AssertionError(impossible);
        }
        acting = true;
        stopWaitingForId = false;
        laneRetryRebind.put(pane, oldId);
        handler.removeCallbacks(poll);
        setIfChanged(error, "");
        updateButtons();
        network.execute(() -> {
            try {
                JSONObject updated = client.post(body);
                handler.post(() -> {
                    acting = false;
                    laneRetryRebind.remove(pane);
                    bindRetriedLane(updated, pane, question); // even if the page is hidden now
                    if (!visible || quitting) return;
                    reachable = true;
                    showSnapshot(updated);
                    schedule(0);
                });
            } catch (IOException | JSONException failure) {
                handler.post(() -> {
                    acting = false;
                    boolean definite = failure instanceof AiClient.ApiException;
                    if (definite) laneRetryRebind.remove(pane); // else a later snapshot may show it
                    if (!visible || quitting) return;
                    error.setText(definite ? failure.getMessage() : getString(R.string.action_failed));
                    renderStatus();
                    updateButtons();
                    schedule(automatic ? 5000 : 2000);
                });
            }
        });
    }

    private void bindRetriedLane(JSONObject updated, String pane, String question) {
        laneHealth.markRetried(pane);
        JSONObject fresh = answerOf(updated, pane);
        if (fresh == null || fresh.optString("id").isEmpty()
                || !question.equals(fresh.optString("question"))
                || !latestRequestedPanes.contains(pane)) return;
        latestRequestIds.put(pane, fresh.optString("id"));
        answerStarts.put(fresh.optString("id"), SystemClock.elapsedRealtime());
        saveLatestRequest();
    }

    private void stopAnswers() {
        if (snapshot == null || !reachable || acting || quitting) return;
        List<String> seenIds = openAnswerIds(snapshot);
        Map<String, String> seenStates = openAnswerStates(snapshot);
        stopWaitingForId = false;
        acting = true;
        handler.removeCallbacks(poll);
        setMainStatus(getString(R.string.stopping));
        updateButtons();
        network.execute(() -> {
            JSONObject updated = null;
            String problem = null;
            List<String> ids = seenIds;
            Map<String, String> states = seenStates;
            if (ids.isEmpty()) {
                try {
                    // An answer may have gained its ID since the last screen update.
                    updated = client.getSnapshot();
                    ids = openAnswerIds(updated);
                    states = openAnswerStates(updated);
                } catch (IOException | JSONException failure) {
                    problem = getString(R.string.action_failed);
                }
            }
            if (!ids.isEmpty()) {
                try {
                    updated = cancelOpenAnswers(ids, states);
                } catch (IOException | JSONException failure) {
                    problem = getString(R.string.stop_failed);
                }
                try {
                    updated = client.getSnapshot();
                    // A cancel refused because the answer just finished is not a failed Stop.
                    if (problem != null && !updated.optBoolean("locked")
                            && !StopPolicy.stillRunning(ids, openAnswerIds(updated))) {
                        problem = null;
                    }
                } catch (IOException | JSONException failure) {
                    if (updated == null && problem == null) {
                        problem = getString(R.string.action_failed);
                    }
                }
            }
            JSONObject finalSnapshot = updated;
            String finalProblem = problem;
            boolean noIdYet = problem == null && usableAnswerSnapshot(finalSnapshot)
                    && StopPolicy.hasOpenWithoutId(openAnswerIdsByPane(finalSnapshot));
            handler.post(() -> {
                acting = false;
                if (!visible || quitting) return;
                stopWaitingForId = noIdYet;
                if (finalSnapshot != null) {
                    reachable = true;
                    showSnapshot(finalSnapshot);
                } else {
                    setMainStatus(getString(R.string.checking_connection));
                }
                if (finalProblem != null) error.setText(finalProblem);
                updateButtons();
                schedule(finalProblem != null ? 2000 : noIdYet ? 500 : 0);
            });
        });
    }

    private void confirmQuit() {
        showAlert(new AlertDialog.Builder(this, R.style.LinkDialogTheme)
                .setTitle(R.string.quit_confirm_title)
                .setMessage(R.string.quit_confirm_message)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.quit_action, (dialog, which) -> quitActivity()));
    }

    private static List<String> openAnswerIds(JSONObject data) {
        Map<String, String> byPane = new HashMap<>();
        for (String pane : paneNames(data)) {
            JSONObject answer = answerOf(data, pane);
            if (open(answer)) byPane.put(pane, answer.optString("id"));
        }
        return PaneKeys.uniqueOpenIds(paneNames(data), byPane);
    }

    private static List<String> openAnswerIdsByPane(JSONObject data) {
        List<String> ids = new ArrayList<>();
        for (String pane : paneNames(data)) {
            JSONObject answer = answerOf(data, pane);
            if (open(answer)) ids.add(answer.optString("id"));
        }
        return ids;
    }

    private static boolean usableAnswerSnapshot(JSONObject data) {
        return data != null && !data.optBoolean("locked")
                && data.optJSONObject("phone") != null && data.optJSONObject("gpu") != null;
    }

    private static Map<String, String> openAnswerStates(JSONObject data) {
        Map<String, String> states = new HashMap<>();
        for (String pane : paneNames(data)) {
            JSONObject answer = answerOf(data, pane);
            if (open(answer) && !answer.optString("id").isEmpty()) {
                states.put(answer.optString("id"), answer.optString("state"));
            }
        }
        return states;
    }

    private static boolean hasOpenAnswer(JSONObject data) {
        for (String pane : paneNames(data)) {
            if (open(answerOf(data, pane))) return true;
        }
        return false;
    }

    private JSONObject cancelOpenAnswers(List<String> ids, Map<String, String> states)
            throws IOException, JSONException {
        try {
            // The current service flags every lane before releasing the phone decoder.
            return client.post(cancelBody(ids));
        } catch (AiClient.ApiException failure) {
            if (!StopPolicy.legacyBulkUnsupported(failure.status, failure.getMessage())) {
                throw failure;
            }
            // Older phone hosts accept one ID at a time. Stop waiting lanes first so
            // ending the active answer does not immediately start the next pool lane.
            JSONObject updated = null;
            IOException firstFailure = null;
            for (String id : StopPolicy.waitingFirst(ids, states)) {
                try {
                    updated = client.post(cancelOneBody(id));
                } catch (IOException | JSONException singleFailure) {
                    if (firstFailure == null) {
                        firstFailure = new IOException("Could not stop every answer", singleFailure);
                    }
                }
            }
            if (firstFailure != null) throw firstFailure;
            return updated;
        }
    }

    private void quitActivity() {
        if (quitting) return;
        quitting = true;
        stopWaitingForId = false;
        handler.removeCallbacks(poll);
        updateButtons();
        quitProgressDialog = new AlertDialog.Builder(this, R.style.LinkDialogTheme)
                .setMessage(R.string.quit_stopping)
                .setCancelable(false)
                .create();
        quitProgressDialog.setCanceledOnTouchOutside(false);
        quitProgressDialog.show();
        typography.defaults(quitProgressDialog.getWindow().getDecorView());
        applyPaletteToAlert(quitProgressDialog);
        JSONObject lastSeen = snapshot;
        network.execute(() -> {
            JSONObject latest = null;
            try {
                latest = client.getSnapshot();
            } catch (IOException | JSONException ignored) {
                // A disconnected service leaves only the IDs visible before Quit.
            }
            // An old screen snapshot can supply IDs, but cannot prove that a new Send ended.
            boolean beforeFresh = usableAnswerSnapshot(latest);
            JSONObject targets = beforeFresh ? latest : lastSeen;
            boolean beforeUsable = usableAnswerSnapshot(targets);
            boolean openBefore = beforeUsable && hasOpenAnswer(targets);
            List<String> ids = beforeUsable ? openAnswerIds(targets) : new ArrayList<>();
            Map<String, String> states = beforeUsable
                    ? openAnswerStates(targets) : new HashMap<>();
            JSONObject updated = null;
            if (!ids.isEmpty()) {
                try {
                    updated = cancelOpenAnswers(ids, states);
                } catch (IOException | JSONException ignored) {
                    // The final snapshot decides whether any answer is still open.
                }
            }
            JSONObject afterCancel = updated;
            if (openBefore || !beforeFresh) {
                try {
                    afterCancel = client.getSnapshot();
                } catch (IOException | JSONException ignored) {
                    // A cancel response may still show that every answer stopped.
                }
            }
            JSONObject finalSnapshot = afterCancel;
            boolean finalCancelFailed = !StopPolicy.quitConfirmedStopped(beforeFresh,
                    openBefore, usableAnswerSnapshot(afterCancel), hasOpenAnswer(afterCancel));
            handler.post(() -> {
                if (isDestroyed()) {
                    if (!finalCancelFailed) finishAndRemoveTask();
                    return;
                }
                if (visible && finalSnapshot != null) showSnapshot(finalSnapshot);
                if (quitProgressDialog != null) {
                    quitProgressDialog.dismiss();
                    quitProgressDialog = null;
                }
                if (finalCancelFailed && !isFinishing()) {
                    quitting = false;
                    updateButtons();
                    schedule(0);
                    showAlert(new AlertDialog.Builder(this, R.style.LinkDialogTheme)
                            .setTitle(R.string.quit_still_running_title)
                            .setMessage(R.string.quit_still_running_message)
                            .setPositiveButton(R.string.try_again, (dialog, which) -> quitActivity())
                            .setNegativeButton(R.string.quit_close_app, (dialog, which) -> finishAndRemoveTask()));
                } else finishAndRemoveTask();
            });
        });
    }

    private void pairingAction(String name) {
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        JSONObject pending = link == null ? null : link.optJSONObject("pending");
        if (pending == null || pairingTimedOut) {
            pairingTimedOut = true;
            showPairingProblem(getString(R.string.pairing_expired), true,
                    R.string.pairing_expired);
            schedule(0);
            return;
        }
        String code = pending.isNull("code") ? "" : pending.optString("code", "");
        if (!PairingPrompt.validCode(code)) {
            showPairingProblem(getString(R.string.pairing_code_missing), false,
                    R.string.pairing_code_missing);
            schedule(0);
            return;
        }
        JSONObject body = action(name);
        try {
            body.put("code", code);
        } catch (JSONException invalid) {
            showPairingProblem(getString(R.string.pairing_confirm_failed), true, 0);
            schedule(0);
            return;
        }
        pairingActionMessage = "";
        pairingActionError = false;
        sendAction(body, null, 0, false);
    }

    private void showPairingProblem(String message, boolean errorTone, int problem) {
        pairingActionMessage = message == null ? "" : message;
        pairingActionError = errorTone;
        lastPairingProblem = problem;
        if (pairing != null && pairing.getVisibility() == View.VISIBLE) {
            setIfChanged(pairingText, pairingActionMessage);
            pairingText.setTextColor(parseHex(errorTone ? palette.error() : palette.ink()));
            pairing.announceForAccessibility(pairingActionMessage);
        } else if (errorTone) {
            setIfChanged(error, pairingActionMessage);
        }
        updateButtons();
    }

    private static JSONObject action(String name) {
        JSONObject body = new JSONObject();
        try {
            body.put("action", name);
        } catch (JSONException impossible) {
            throw new AssertionError(impossible);
        }
        return body;
    }

    /** One cancel request naming every open answer, so flags are set before the decode gate is released. */
    private static JSONObject cancelBody(List<String> ids) {
        JSONObject body = action("cancel");
        try {
            JSONArray array = new JSONArray();
            for (String id : ids) array.put(id);
            body.put("ids", array);
        } catch (JSONException impossible) {
            throw new AssertionError(impossible);
        }
        return body;
    }

    private static JSONObject cancelOneBody(String id) {
        JSONObject body = action("cancel");
        try {
            body.put("id", id);
        } catch (JSONException impossible) {
            throw new AssertionError(impossible);
        }
        return body;
    }

    private void sendAction(JSONObject body, String sentQuestion, long startedAtMs,
                            boolean retrying) {
        if (!visible || !reachable || acting || quitting) return;
        stopWaitingForId = false;
        String draftAtSubmission = sentQuestion != null && !retrying
                ? prompt.getText().toString() : null;
        long submittedRevision = draftRevision;
        long submittedAtWallMs = System.currentTimeMillis();
        JSONObject beforeAtTap = snapshot;
        boolean needsReconcile = sentQuestion != null && askRecovery.unresolved();
        Map<String, String> retryIds = new HashMap<>();
        Map<String, String> retryStates = new HashMap<>();
        if (retrying && !needsReconcile && snapshot != null) {
            JSONArray panes = body.optJSONArray("panes");
            for (int index = 0; panes != null && index < panes.length(); index++) {
                String pane = panes.optString(index);
                JSONObject answer = answerOf(snapshot, pane);
                retryIds.put(pane, answer == null ? "" : answer.optString("id"));
                retryStates.put(pane, answer == null ? "" : answer.optString("state"));
            }
        }
        if (sentQuestion != null) {
            clearedDraftRevision = -1;
            clearedDraft = "";
        }
        acting = true;
        handler.removeCallbacks(poll);
        setIfChanged(error, "");
        if (sentQuestion != null) setMainStatus(getString(needsReconcile
                ? R.string.answer_ack_uncertain : R.string.thinking));
        updateButtons();
        network.execute(() -> {
            if (needsReconcile) {
                try {
                    JSONObject checked = client.getSnapshot();
                    handler.post(() -> {
                        acting = false;
                        if (!visible || quitting) return;
                        reachable = true;
                        showSnapshot(checked);
                        if (askRecovery.unresolved()) {
                            error.setText(R.string.answer_ack_uncertain);
                        }
                        schedule(0);
                    });
                } catch (IOException | JSONException failure) {
                    handler.post(() -> {
                        acting = false;
                        if (!visible || quitting) return;
                        reachable = false;
                        showOffline(failure);
                        schedule(2000);
                    });
                }
                return; // Both Send and Try again stop at this reconciliation boundary.
            }
            JSONObject prePost = beforeAtTap;
            if (retrying) {
                try {
                    JSONObject checked = client.getSnapshot();
                    if (retryChanged(checked, body.optJSONArray("panes"), sentQuestion,
                            retryIds, retryStates)) {
                        handler.post(() -> {
                            acting = false;
                            if (!visible || quitting) return;
                            reachable = true;
                            showSnapshot(checked);
                            schedule(0);
                        });
                        return;
                    }
                    prePost = checked;
                } catch (IOException | JSONException failure) {
                    handler.post(() -> {
                        acting = false;
                        if (!visible || quitting) return;
                        reachable = false;
                        showOffline(failure);
                        schedule(2000);
                    });
                    return;
                }
            }
            PendingAsk submitted = sentQuestion == null ? null : new PendingAsk(
                    prePost, body.optJSONArray("panes"), sentQuestion, startedAtMs,
                    submittedAtWallMs, retrying, draftAtSubmission, submittedRevision);
            try {
                if (submitted != null && !getPreferences(MODE_PRIVATE).edit()
                        .putBoolean(PREF_UNRESOLVED_ASK, true).commit()) {
                    throw new IOException("Could not save Send state");
                }
                JSONObject updated = client.post(body);
                handler.post(() -> {
                    acting = false;
                    if (submitted != null) {
                        pendingAsk = null;
                        askRecovery.resolve();
                        getPreferences(MODE_PRIVATE).edit()
                                .putBoolean(PREF_UNRESOLVED_ASK, false).apply();
                    }
                    // Bind the new answer IDs even when folded or in the background, so the
                    // answers this Send started are not shown as "Not asked this time" later.
                    boolean bound = sentQuestion != null && !updated.optBoolean("locked");
                    if (bound) {
                        lastSubmittedQuestion = sentQuestion;
                        rememberStarts(updated, body.optJSONArray("panes"), sentQuestion,
                                startedAtMs, submittedAtWallMs, retrying, submitted.before,
                                null);
                        if (!isDestroyed()) clearDraftIfUntouched(draftAtSubmission, submittedRevision);
                    }
                    if (!visible || quitting) return;
                    reachable = true;
                    showSnapshot(updated);
                    schedule(0);
                });
            } catch (IOException | JSONException failure) {
                JSONObject refreshed = null;
                if (sentQuestion != null && !(failure instanceof AiClient.ApiException)) {
                    try {
                        refreshed = client.getSnapshot();
                    } catch (IOException | JSONException ignored) {
                        // The POST may still have reached the phone. Later polls can reconcile it.
                    }
                }
                JSONObject reconciled = refreshed;
                handler.post(() -> {
                    acting = false;
                    boolean uncertain = sentQuestion != null
                            && !(failure instanceof AiClient.ApiException);
                    if (uncertain) {
                        pendingAsk = submitted;
                        askRecovery.markUncertain(submitted.attempt);
                    } else if (submitted != null) {
                        getPreferences(MODE_PRIVATE).edit()
                                .putBoolean(PREF_UNRESOLVED_ASK, false).apply();
                    }
                    if (!visible || quitting) return;
                    if (uncertain) {
                        if (reconciled != null) {
                            reachable = true;
                            showSnapshot(reconciled);
                        } else {
                            reachable = false;
                            showOffline(failure);
                        }
                        schedule(0);
                        return;
                    }
                    boolean pairingDecision = "allow".equals(body.optString("action"))
                            || "deny".equals(body.optString("action"));
                    if (pairingDecision) {
                        boolean oldCode = failure instanceof AiClient.ApiException
                                && PairingPrompt.oldRequest(failure.getMessage());
                        if (oldCode) {
                            if ("allow".equals(body.optString("action"))) {
                                rejectedPairingCode = PairingPrompt.formatCode(body.optString("code"));
                                showPairingProblem(getString(R.string.pairing_code_mismatch),
                                        true, R.string.pairing_code_mismatch);
                            }
                        } else {
                            String message = failure instanceof AiClient.ApiException
                                    ? failure.getMessage() : null;
                            if (message == null || message.trim().isEmpty()) {
                                message = getString(R.string.pairing_confirm_failed);
                            }
                            showPairingProblem(message, true, 0);
                        }
                        if (oldCode && "deny".equals(body.optString("action"))) {
                            allow.setEnabled(false);
                            deny.setEnabled(false);
                        }
                        schedule(0);
                        return;
                    }
                    error.setText(failure instanceof AiClient.ApiException
                            ? failure.getMessage() : getString(R.string.action_failed));
                    renderStatus();
                    updateButtons();
                    schedule(2000);
                });
            }
        });
    }

    private static boolean retryChanged(JSONObject checked, JSONArray requested,
                                        String question, Map<String, String> beforeIds,
                                        Map<String, String> beforeStates) {
        if (checked.optBoolean("locked") || checked.optJSONObject("phone") == null
                || checked.optJSONObject("gpu") == null) return true;
        for (int index = 0; requested != null && index < requested.length(); index++) {
            String pane = requested.optString(index);
            JSONObject answer = answerOf(checked, pane);
            if (answer == null) continue;
            String id = answer.optString("id");
            if (!id.isEmpty() && !id.equals(beforeIds.get(pane))) return true;
            if (open(answer) && !id.isEmpty()) return true;
            if (!question.equals(answer.optString("question"))) continue;
            if ("failed".equals(beforeStates.get(pane))
                    && !"failed".equals(answer.optString("state"))) return true;
        }
        return false;
    }

    private void clearDraftIfUntouched(String draft, long submittedRevision) {
        if (draft == null) return;
        if (submittedRevision != draftRevision || !draft.equals(prompt.getText().toString())) {
            return;
        }
        prompt.setText("");
        clearedDraft = draft;
        clearedDraftRevision = draftRevision;
        hideKeyboard();
    }

    private void rememberStarts(JSONObject updated, JSONArray requested,
                                String sentQuestion, long startedAtMs,
                                long submittedAtWallMs, boolean retrying,
                                JSONObject before, Set<String> bindablePanes) {
        if (requested == null) return;
        questionStartedAtMs = startedAtMs;
        overallElapsedMs = -1;
        if (!retrying) {
            laneHealth.reset();
            laneRetryRebind.clear();
            latestRequestIds.clear();
            latestRequestedPanes.clear();
            previousAnswerIds.clear();
            displayedPanes.clear();
            for (int index = 0; index < requested.length(); index++) {
                String pane = requested.optString(index);
                if (PaneKeys.valid(pane) && !displayedPanes.contains(pane)) displayedPanes.add(pane);
            }
            displayPinned = true;
            archivedIssueId = "";
        }
        latestRequestAtWallMs = submittedAtWallMs;
        latestRequestAtElapsedMs = SystemClock.elapsedRealtime();
        for (int index = 0; index < requested.length(); index++) {
            String pane = requested.optString(index);
            if (!PaneKeys.valid(pane)) continue;
            latestRequestedPanes.add(pane);
            latestRequestIds.remove(pane);
            JSONObject previousAnswer = answerOf(before, pane);
            String previousId = previousAnswer == null ? "" : previousAnswer.optString("id");
            previousAnswerIds.put(pane, previousId);
            JSONObject answer = answerOf(updated, pane);
            if (answer == null || !sentQuestion.equals(answer.optString("question"))) continue;
            String id = answer.optString("id");
            if (!id.isEmpty() && !id.equals(previousId)
                    && (bindablePanes == null || bindablePanes.contains(pane))) {
                latestRequestIds.put(pane, id);
                answerStarts.put(id, startedAtMs);
            }
        }
        saveLatestRequest();
    }

    private void hideKeyboard() {
        InputMethodManager keyboard =
                (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(prompt.getWindowToken(), 0);
        prompt.clearFocus();
    }

    private LinearLayout pageRoot() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(themeColor(R.color.newspaper_paper));
        root.setPadding(dp(16), dp(12), dp(16), dp(12));
        // Full-screen sheets start below the status bar and end above the navigation bar,
        // like the Info sheet (fitsSystemWindows in gpu_link_info.xml).
        padForSystemBars(root);
        return root;
    }

    /**
     * Keep a full-screen sheet below the status bar and above the navigation bar while keeping
     * its own padding. (fitsSystemWindows would replace the 16 dp side padding with the insets.)
     */
    private static void padForSystemBars(View view) {
        final int left = view.getPaddingLeft();
        final int top = view.getPaddingTop();
        final int right = view.getPaddingRight();
        final int bottom = view.getPaddingBottom();
        view.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(left + insets.getSystemWindowInsetLeft(),
                    top + insets.getSystemWindowInsetTop(),
                    right + insets.getSystemWindowInsetRight(),
                    bottom + insets.getSystemWindowInsetBottom());
            return insets;
        });
        view.requestApplyInsets();
    }

    private Button outlineButton(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        button.setTypeface(typography.interSemibold);
        styleChromeOutline(button);
        button.setMinHeight(dp(48));
        button.setMinimumHeight(dp(48));
        return button;
    }

    private LinearLayout pageBar(String title, String closeLabel, View.OnClickListener close) {
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        TextView heading = newspaperText(title, typography.headingSp(), true, true);
        heading.setAccessibilityHeading(true);
        bar.addView(heading, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        Button exit = outlineButton(closeLabel);
        exit.setOnClickListener(close);
        bar.addView(exit, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, dp(48)));
        return bar;
    }

    private void showFullPage(Dialog dialog, LinearLayout root) {
        dialog.setContentView(root);
        Window window = dialog.getWindow();
        if (window != null) window.setWindowAnimations(0);
        dialog.show();
        if (window != null) {
            window.setBackgroundDrawableResource(R.color.newspaper_paper);
            window.setLayout(WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT);
        }
    }

    private void showModelSelection() {
        if (modelSelectionDialog != null && modelSelectionDialog.isShowing()) return;
        Dialog dialog = new Dialog(this, R.style.NewspaperDialogTheme);
        modelSelectionDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (modelSelectionDialog == dialog) {
                modelSelectionDialog = null;
                modelRows = null;
                modelSelectionNotice = null;
                modelRowPanes.clear();
                modelReadyHints.clear();
                modelToggles.clear();
                modelLabels.clear();
                modelMetaViews.clear();
            }
        });
        LinearLayout root = pageRoot();
        root.addView(pageBar("Model Selection", "Close", view -> dialog.dismiss()));
        View rule = new View(this);
        rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
        LinearLayout.LayoutParams ruleParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1));
        ruleParams.topMargin = dp(12);
        root.addView(rule, ruleParams);
        TextView note = newspaperText(
                "Phone models answer one at a time. Computer models can answer together.",
                15, false, false);
        note.setPadding(0, dp(14), 0, dp(10));
        root.addView(note);
        modelSelectionNotice = newspaperText("", 14, true, false);
        root.addView(modelSelectionNotice);
        ScrollView scroll = new ScrollView(this);
        modelRows = new LinearLayout(this);
        modelRows.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(modelRows);
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        showFullPage(dialog, root);
        updateModelSelectionRows();
    }

    private List<String> groupedModelPanes() {
        List<String> available = paneNames(snapshot);
        List<String> result = new ArrayList<>();
        result.add("phone");
        for (String pane : available) {
            if (PaneKeys.extra(pane) && !PaneKeys.pc(pane)) result.add(pane);
        }
        result.add("gpu");
        for (String pane : available) {
            if (PaneKeys.extra(pane) && PaneKeys.pc(pane)) result.add(pane);
        }
        return result;
    }

    private String modelLabel(String pane, JSONObject view) {
        if ("phone".equals(pane)) {
            String model = PhoneByline.modelName(phoneSelectionModel(view));
            return model.isEmpty() ? getString(R.string.phone_heading) : model;
        }
        if ("gpu".equals(pane)) return leadTitle(view);
        String label = ModelDisplay.firstNonBlank(textField(view, "label"),
                textField(view, "model"));
        return label.isEmpty() ? PaneKeys.fallbackLabel(pane) : ModelDisplay.label(label);
    }

    private String phoneSelectionModel(JSONObject view) {
        JSONObject answer = view == null ? null : view.optJSONObject("answer");
        return PhoneByline.cardModel(textField(view, "model"), textField(answer, "model"),
                answer != null, answer != null && answerShown("phone", answer));
    }

    private String modelDetails(String pane, JSONObject view) {
        String model = "phone".equals(pane) ? phoneSelectionModel(view)
                : ModelDisplay.firstNonBlank(
                        PaneKeys.extra(pane) ? textField(view, "label") : "",
                        textField(view, "model"));
        String maker = "phone".equals(pane) ? PhoneByline.maker(model)
                : textField(view, "maker");
        String where = PaneKeys.shownWhere(pane, textField(view, "where"));
        StringBuilder details = new StringBuilder(
                ModelMaker.details("", ModelMaker.maker(maker, model), where));
        double fileMb = view == null ? Double.NaN : view.optDouble("file_mb", Double.NaN);
        if (Double.isFinite(fileMb) && fileMb >= 0) {
            if (details.length() > 0) details.append(" · ");
            details.append(fileMb == Math.rint(fileMb)
                    ? String.format(Locale.US, "%.0f MB", fileMb)
                    : String.format(Locale.US, "%.1f MB", fileMb));
        }
        return details.toString();
    }

    private static String textField(JSONObject object, String key) {
        return object == null || object.isNull(key) ? "" : object.optString(key).trim();
    }

    private void addModelSection(String heading) {
        TextView section = newspaperText(heading, 24, true, true);
        section.setAccessibilityHeading(true);
        section.setPadding(0, dp(18), 0, dp(8));
        modelRows.addView(section);
        View rule = new View(this);
        rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
        modelRows.addView(rule, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
    }

    private void addModelRow(String pane) {
        JSONObject view = paneOf(snapshot, pane);
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(14), 0, dp(14));
        LinearLayout details = new LinearLayout(this);
        details.setOrientation(LinearLayout.VERTICAL);
        TextView title = newspaperText(modelLabel(pane, view), 21, true, true);
        details.addView(title);
        modelLabels.put(pane, title);
        TextView meta = newspaperText(modelDetails(pane, view), 13, false, false);
        typography.tabular(meta);
        details.addView(meta);
        modelMetaViews.put(pane, meta);
        TextView ready = newspaperText("", 13, true, false);
        details.addView(ready);
        modelReadyHints.put(pane, ready);
        row.addView(details, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1));
        TextView toggle = newspaperText("", 14, true, false);
        toggle.setGravity(Gravity.CENTER);
        toggle.setFocusable(true);
        toggle.setAccessibilityDelegate(new View.AccessibilityDelegate() {
            @Override public void onInitializeAccessibilityNodeInfo(View host,
                    AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(android.widget.Switch.class.getName());
                info.setCheckable(true);
                info.setChecked(Boolean.TRUE.equals(host.getTag(R.id.model_toggle_selected)));
            }
            @Override public void onInitializeAccessibilityEvent(View host,
                    android.view.accessibility.AccessibilityEvent event) {
                super.onInitializeAccessibilityEvent(host, event);
                event.setClassName(android.widget.Switch.class.getName());
                event.setChecked(Boolean.TRUE.equals(host.getTag(R.id.model_toggle_selected)));
            }
        });
        toggle.setOnClickListener(tapped -> {
            List<String> available = paneNames(snapshot);
            Map<String, Boolean> readyNow = readyPanes(snapshot);
            boolean next = !laneSelection.isOn(available, readyNow, pane);
            if (!laneSelection.set(available, readyNow, pane, next)) {
                setIfChanged(modelSelectionNotice, getString(R.string.model_selection_minimum));
                return;
            }
            setIfChanged(modelSelectionNotice, getString(R.string.model_selection_next_question));
            updateModelSelectionRows();
            if (!displayPinned && snapshot != null) syncModelViews(snapshot);
            updateButtons();
        });
        row.addView(toggle, new LinearLayout.LayoutParams(dp(64), dp(48)));
        modelToggles.put(pane, toggle);
        modelRows.addView(row);
        View rule = new View(this);
        rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
        modelRows.addView(rule, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
    }

    private void updateModelSelectionRows() {
        if (modelSelectionDialog == null || !modelSelectionDialog.isShowing()
                || modelRows == null) return;
        List<String> grouped = groupedModelPanes();
        if (!grouped.equals(modelRowPanes)) {
            modelRowPanes.clear();
            modelRowPanes.addAll(grouped);
            modelReadyHints.clear();
            modelToggles.clear();
            modelLabels.clear();
            modelMetaViews.clear();
            modelRows.removeAllViews();
            addModelSection("This phone");
            for (String pane : grouped) {
                if (PaneKeys.pc(pane)) continue;
                addModelRow(pane);
            }
            addModelSection(getString(R.string.gpu_heading_neutral));
            for (String pane : grouped) {
                if (PaneKeys.pc(pane)) addModelRow(pane);
            }
        }
        List<String> available = paneNames(snapshot);
        Map<String, Boolean> ready = readyPanes(snapshot);
        for (String pane : grouped) {
            JSONObject view = paneOf(snapshot, pane);
            TextView label = modelLabels.get(pane);
            if (label != null) setIfChanged(label, modelLabel(pane, view));
            TextView meta = modelMetaViews.get(pane);
            if (meta != null) setIfChanged(meta, modelDetails(pane, view));
            TextView hint = modelReadyHints.get(pane);
            if (hint != null) setIfChanged(hint, reachable && !offline
                    && view != null && view.optBoolean("ready")
                    ? getString(R.string.ready_to_ask) : "Not ready");
            TextView toggle = modelToggles.get(pane);
            if (toggle == null) continue;
            boolean on = laneSelection.isOn(available, ready, pane);
            setIfChanged(toggle, on ? "ON" : "OFF");
            toggle.setTextColor(on ? themeColor(R.color.newspaper_paper) : themeColor(R.color.newspaper_ink));
            toggle.setBackgroundResource(on ? R.drawable.newspaper_primary
                    : R.drawable.newspaper_outline);
            toggle.setTag(R.id.model_toggle_selected, on);
            toggle.setContentDescription(modelLabel(pane, view));
        }
    }

    private String issueDate(long askedAtMs) {
        return DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
                .format(new Date(askedAtMs));
    }

    private void showHistory() {
        if (historyDialog != null && historyDialog.isShowing()) return;
        Dialog dialog = new Dialog(this, R.style.NewspaperDialogTheme);
        historyDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (historyDialog == dialog) {
                historyDialog = null;
                historyRows = null;
            }
        });
        LinearLayout root = pageRoot();
        root.addView(pageBar(getString(R.string.history_title), getString(R.string.close),
                view -> dialog.dismiss()));
        // Palette and typography follow the current theme.
        TextView note = newspaperText(getString(R.string.history_subtitle), 14, false, false);
        note.setPadding(0, dp(10), 0, dp(10));
        root.addView(note);
        View rule = new View(this);
        rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
        root.addView(rule, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        ScrollView scroll = new ScrollView(this);
        historyRows = new LinearLayout(this);
        historyRows.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(historyRows);
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        Button clear = outlineButton(getString(R.string.history_clear_action));
        clear.setOnClickListener(view -> showAlert(new AlertDialog.Builder(this, R.style.LinkDialogTheme)
                .setTitle(R.string.history_clear_title)
                .setMessage(R.string.history_clear_message)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.history_clear_action, (confirmed, which) -> {
                    String currentId = latestRequestAtWallMs > 0
                            ? Long.toString(latestRequestAtWallMs) : "";
                    suppressedIssueId = historyStore.contains(currentId) ? currentId : "";
                    historyStore.clear(suppressedIssueId);
                    fillHistoryRows();
                })));
        LinearLayout.LayoutParams clearParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(48));
        clearParams.topMargin = dp(10);
        root.addView(clear, clearParams);
        showFullPage(dialog, root);
        applyPaletteToDialog(dialog);
        fillHistoryRows();
    }

    private void fillHistoryRows() {
        if (historyRows == null) return;
        historyRows.removeAllViews();
        List<HistoryStore.Issue> issues = historyStore.list();
        if (issues.isEmpty()) {
            TextView empty = newspaperText(getString(R.string.history_empty), 18, false, true);
            empty.setPadding(0, dp(24), 0, 0);
            historyRows.addView(empty);
            return;
        }
        for (HistoryStore.Issue issue : issues) {
            BackIssue mapped = BackIssue.from(issue);
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.VERTICAL);
            row.setPadding(dp(8), dp(16), dp(8), dp(16));
            row.setFocusable(true);
            row.setClickable(true);
            String savedHeadline = mapped.headline == null ? "" : mapped.headline.trim();
            row.setContentDescription(savedHeadline.isEmpty()
                    ? getString(R.string.history_open_untitled_description,
                            issueDate(issue.askedAtMs))
                    : getString(R.string.history_open_description,
                            savedHeadline, issueDate(issue.askedAtMs)));
            TextView date = newspaperText(issueDate(issue.askedAtMs), 13, true, false);
            typography.tabular(date);
            row.addView(date);
            TextView headline = newspaperText(mapped.headline, 23, true, true);
            setQuestionHeadline(headline, mapped.headline);
            row.addView(headline);
            row.addView(newspaperText(getString(R.string.history_answered_by, mapped.answeredBy),
                    13, false, false));
            if (!issue.sourceId.isEmpty()) {
                TextView link = newspaperText(getString(R.string.history_linked_refresh), 13, false, false);
                link.setTextColor(themeColor(R.color.you_asked_label));
                row.addView(link);
            }
            final HistoryStore.Issue opened = issue;
            row.setOnClickListener(view -> {
                if (historyDialog != null) historyDialog.dismiss();
                showBackIssue(opened);
            });
            historyRows.addView(row);
            View rule = new View(this);
            rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
            historyRows.addView(rule, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(1)));
        }
    }

    private LinearLayout savedBox() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(LaneCardLayout.CARD_PADDING_DP);
        box.setPadding(pad, pad, pad, pad);
        box.setBackground(panelDrawable(palette.stroke()));
        enableSmoothGrowth(box);
        return box;
    }

    private LinearLayout savedArticle(HistoryStore.Lane lane) {
        LinearLayout card = savedBox();
        // A saved answer keeps the noun of the computer that wrote it, when known.
        String laneWhere = PaneKeys.archivedWhere(lane.where);
        String laneComputer = PaneKeys.archivedComputer(lane.where);
        TextView kicker = newspaperText(PaneKeys.kicker(lane.pane, laneComputer),
                LaneCardLayout.LABEL_SP, true, false);
        typography.kicker(kicker);
        card.addView(kicker);
        card.addView(newspaperText(HistoryDisplay.label(lane), LaneCardLayout.headingSp(PaneKeys.extra(lane.pane),
                "gpu".equals(lane.pane)), true, true));
        String savedMaker = HistoryDisplay.maker(lane);
        String byline = savedMaker.isEmpty() ? laneWhere
                : laneWhere.isEmpty() ? savedMaker : savedMaker + " · " + laneWhere;
        TextView bylineView = newspaperText(byline, LaneCardLayout.LABEL_SP, false, false);
        typography.byline(bylineView);
        card.addView(bylineView);
        TextView stateView = newspaperText(lane.state, LaneCardLayout.LABEL_SP, true, false);
        typography.state(stateView);
        typography.tabular(stateView);
        applyTone(stateView);
        card.addView(stateView);
        if (lane.truncated) {
            TextView excerpt = newspaperText(getString(R.string.history_answer_shortened),
                    LaneCardLayout.LABEL_SP, true, false);
            typography.tabular(excerpt);
            card.addView(excerpt);
        }
        TextView answer = newspaperText("", LaneCardLayout.BODY_SP_FULL, false, true);
        typography.body(answer, LaneCardLayout.BODY_SP_FULL);
        answer.setTextIsSelectable(true);
        setMarkdownAnswer(answer, AnswerDisplay.text(lane.pane, lane.text));
        LinearLayout.LayoutParams bodyParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        bodyParams.topMargin = dp(6);
        card.addView(answer, bodyParams);
        return card;
    }

    private void showBackIssue(HistoryStore.Issue saved) {
        BackIssue issue = BackIssue.from(saved);
        Dialog dialog = new Dialog(this, R.style.NewspaperDialogTheme);
        backIssueDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (backIssueDialog == dialog) backIssueDialog = null;
        });
        LinearLayout root = pageRoot();
        root.addView(pageBar(getString(R.string.app_name), getString(R.string.history_back_to_today),
                view -> dialog.dismiss()));
        View rule = new View(this);
        rule.setBackgroundColor(themeColor(R.color.newspaper_stroke));
        LinearLayout.LayoutParams lineParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(1));
        lineParams.topMargin = dp(10);
        root.addView(rule, lineParams);
        ScrollView scroll = new ScrollView(this);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        TextView date = newspaperText(getString(R.string.history_back_issue_date,
                        issueDate(saved.askedAtMs)),
                13, true, false);
        typography.tabular(date);
        date.setPadding(0, dp(10), 0, 0);
        page.addView(date);
        TextView headline = newspaperText(issue.headline, 26, true, true);
        setQuestionHeadline(headline, issue.headline);
        headline.setPadding(0, dp(6), 0, dp(10));
        page.addView(headline);
        if (!saved.sourceId.isEmpty()) {
            TextView linked = newspaperText(getString(R.string.history_linked_refresh), 13, false, false);
            linked.setTextColor(themeColor(R.color.you_asked_label));
            page.addView(linked);
        }
        Button refresh = outlineButton(getString(R.string.history_refresh));
        typography.retry(refresh);
        refresh.setContentDescription(getString(R.string.history_refresh_description));
        refresh.setEnabled(HistoryRefresh.canRefresh(saved));
        final HistoryStore.Issue target = saved;
        refresh.setOnClickListener(view -> refreshHistoryIssue(target, dialog));
        LinearLayout.LayoutParams refreshParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        refreshParams.topMargin = dp(8);
        refreshParams.bottomMargin = dp(10);
        page.addView(refresh, refreshParams);
        addThenVersusNow(page, saved);
        LinearLayout timing = savedBox();
        TextView timingKicker = newspaperText(getString(R.string.tonight_label), 12, true, false);
        typography.kicker(timingKicker);
        timing.addView(timingKicker);
        TextView timingCount = newspaperText(issue.elapsed, 28, true, false);
        typography.tabular(timingCount);
        timing.addView(timingCount);
        if (!issue.elapsedLabel.isEmpty()) {
            timing.addView(newspaperText(issue.elapsedLabel, 13, false, false));
        }
        LinearLayout timingRows = new LinearLayout(this);
        timingRows.setOrientation(LinearLayout.VERTICAL);
        timingRows.setPadding(0, dp(6), 0, 0);
        fillTonightRows(timingRows, issue.timing, null);
        timing.addView(timingRows);
        timing.setMinimumHeight(dp(BACK_ISSUE_TIMING_MIN_DP));
        if (compactLayout) {
            page.addView(timing, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            for (HistoryStore.Lane lane : issue.lanes) {
                putWrapCard(page, savedArticle(lane), LaneCardLayout.MIN_LANE_DP,
                        LaneCardLayout.CARD_GAP_DP);
            }
        } else {
            LinearLayout columns = new LinearLayout(this);
            LinearLayout left = new LinearLayout(this);
            left.setOrientation(LinearLayout.VERTICAL);
            LinearLayout right = new LinearLayout(this);
            right.setOrientation(LinearLayout.VERTICAL);
            columns.addView(left, new LinearLayout.LayoutParams(0,
                    LinearLayout.LayoutParams.WRAP_CONTENT, 0.42f));
            LinearLayout.LayoutParams rightParams = new LinearLayout.LayoutParams(0,
                    LinearLayout.LayoutParams.WRAP_CONTENT, 0.58f);
            rightParams.leftMargin = dp(LaneCardLayout.CARD_GAP_DP);
            columns.addView(right, rightParams);
            page.addView(columns);
            left.addView(timing, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            LinearLayout archive = savedBox();
            archive.addView(newspaperText(getString(R.string.history_archive_label), 21, true, true));
            TextView archiveDate = newspaperText(issueDate(saved.askedAtMs), 15, false, false);
            typography.tabular(archiveDate);
            archive.addView(archiveDate);
            archive.addView(newspaperText(getString(R.string.history_answered_by, issue.answeredBy),
                    15, false, false));
            putWrapCard(left, archive, BACK_ISSUE_ARCHIVE_MIN_DP, LaneCardLayout.CARD_GAP_DP);
            for (HistoryStore.Lane lane : issue.lanes) {
                if ("phone".equals(lane.pane)) {
                    putWrapCard(right, savedArticle(lane), LaneCardLayout.MIN_LANE_DP, 0);
                }
            }
            for (HistoryStore.Lane lane : issue.lanes) {
                if ("gpu".equals(lane.pane)) {
                    putWrapCard(right, savedArticle(lane), LaneCardLayout.MIN_LANE_DP,
                            saved.lanes.stream().anyMatch(item -> "phone".equals(item.pane))
                                    ? LaneCardLayout.CARD_GAP_DP : 0);
                }
            }
            int extra = 0;
            for (HistoryStore.Lane lane : issue.lanes) {
                if (!PaneKeys.extra(lane.pane)) continue;
                putWrapCard(extra % 2 == 0 ? left : right, savedArticle(lane),
                        LaneCardLayout.MIN_LANE_DP, LaneCardLayout.CARD_GAP_DP);
                extra++;
            }
        }
        LinearLayout summary = savedBox();
        summary.addView(newspaperText(getString(R.string.summary_label), 21, true, true));
        TextView summaryLine = newspaperText(getString(R.string.history_answered_by, issue.answeredBy),
                13, false, false);
        typography.tabular(summaryLine);
        summary.addView(summaryLine);
        putWrapCard(page, summary, BACK_ISSUE_SUMMARY_MIN_DP, LaneCardLayout.CARD_GAP_DP);
        scroll.addView(page);
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        showFullPage(dialog, root);
        applyPaletteToDialog(dialog);
    }

    private void refreshHistoryIssue(HistoryStore.Issue saved, Dialog dialog) {
        String payload = HistoryRefresh.payload(saved);
        if (payload.isEmpty()) {
            error.setText(R.string.history_refresh_not_sent);
            applyErrorView();
            return;
        }
        pendingRefreshSourceId = HistoryRefresh.rootId(saved);
        pendingRefreshQuestion = payload;
        if (dialog != null) dialog.dismiss();
        if (historyDialog != null) historyDialog.dismiss();
        if (sendQuestion(payload, false)) return;
        pendingRefreshSourceId = "";
        pendingRefreshQuestion = "";
        if (error.getText() == null || error.getText().length() == 0) {
            error.setText(R.string.history_refresh_not_sent);
        }
        applyErrorView();
    }

    private void addThenVersusNow(LinearLayout page, HistoryStore.Issue saved) {
        List<HistoryStore.Issue> issues = historyStore.list();
        HistoryStore.Issue thenIssue = HistoryRefresh.originalOf(issues, saved);
        HistoryStore.Issue nowIssue = saved.sourceId.isEmpty()
                ? HistoryRefresh.latestRefresh(issues, saved) : saved;
        if (thenIssue == null || nowIssue == null || thenIssue.id.equals(nowIssue.id)) return;
        TextView heading = newspaperText(getString(R.string.history_then_vs_now), 21, true, true);
        heading.setAccessibilityHeading(true);
        heading.setPadding(0, dp(8), 0, dp(8));
        typography.headline(heading, typography.headingSp());
        page.addView(heading);
        for (HistoryRefresh.LaneCompare row : HistoryRefresh.compare(thenIssue, nowIssue)) {
            page.addView(thenNowCard(row), new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            ((LinearLayout.LayoutParams) page.getChildAt(page.getChildCount() - 1)
                    .getLayoutParams()).bottomMargin = dp(LaneCardLayout.CARD_GAP_DP);
        }
    }

    private LinearLayout thenNowCard(HistoryRefresh.LaneCompare row) {
        LinearLayout card = savedBox();
        // The two saved runs may have used different computers.
        TextView kicker = newspaperText(PaneKeys.kicker(row.pane, ComputerWords.COMPUTER),
                typography.labelSp(), true, false);
        typography.kicker(kicker);
        card.addView(kicker);
        card.addView(thenNowBlock(row.pane, getString(R.string.history_then),
                row.thenLabel,
                row.presentThen ? row.thenState : getString(R.string.history_not_asked_then),
                row.presentThen ? row.thenText : "",
                row.thenTone));
        card.addView(thenNowBlock(row.pane, getString(R.string.history_now),
                row.nowLabel,
                row.presentNow ? row.nowState : getString(R.string.history_not_asked_now),
                row.presentNow ? row.nowText : "",
                row.nowTone));
        return card;
    }

    private LinearLayout thenNowBlock(String pane, String heading, String modelLabel, String state,
                                      String body, UiPalette.Tone tone) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.VERTICAL);
        block.setPadding(0, dp(8), 0, 0);
        TextView label = newspaperText(heading, typography.labelSp(), true, false);
        typography.kicker(label);
        label.setAccessibilityHeading(true);
        block.addView(label);
        if (modelLabel != null && !modelLabel.isEmpty()) {
            block.addView(newspaperText(modelLabel, typography.headingSp(), true, true));
        }
        TextView stateView = newspaperText(state, typography.labelSp(), true, false);
        typography.state(stateView);
        typography.tabular(stateView);
        stateView.setTextColor(parseHex(palette.colorForTone(tone)));
        block.addView(stateView);
        if (!body.isEmpty()) {
            TextView answer = newspaperText("", typography.bodySp(), false, true);
            typography.body(answer, typography.bodySp());
            answer.setTextIsSelectable(true);
            setMarkdownAnswer(answer, AnswerDisplay.text(pane, body));
            block.addView(answer);
        }
        return block;
    }

    private void showInfo() {
        if (infoDialog != null && infoDialog.isShowing()) return;
        Dialog dialog = new Dialog(this, R.style.InfoDialogTheme);
        infoDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (infoDialog == dialog) infoDialog = null;
        });
        dialog.setContentView(R.layout.gpu_link_info);
        pcLabelStatic(dialog.getWindow().getDecorView(), new int[][]{
                {R.id.info_forget_pc, R.string.forget_pc},
                {R.id.info_replace_pc_steps, R.string.info_replace_pc_steps}});
        pcLabelled(dialog.findViewById(R.id.info_pc_label_text), "PC");
        pcLabelled(dialog.findViewById(R.id.info_pc_id_label_text), "PC ID");
        pcLabelled(dialog.findViewById(R.id.info_pc_status_label_text), "PC status");
        typography.defaults(dialog.getWindow().getDecorView());
        applyPaletteToDialog(dialog);
        typography.headline(dialog.findViewById(R.id.info_page_title), typography.headingSp());
        int[] labels = {
                R.id.info_about_label_text, R.id.info_phone_model_label_text,
                R.id.info_pc_label_text, R.id.info_pc_id_label_text,
                R.id.info_pc_status_label_text, R.id.info_pairing_label_text,
                R.id.info_app_version_label_text, R.id.info_local_service_label_text,
                R.id.info_keep_screen_on_label_text, R.id.info_screen_timeout_label_text,
                R.id.info_cover_layout_label_text
        };
        for (int id : labels) typography.kicker(dialog.findViewById(id));
        int[] values = {
                R.id.info_about, R.id.info_wireless_note, R.id.info_phone_model,
                R.id.info_pc, R.id.info_pc_id, R.id.info_pc_status,
                R.id.info_pairing, R.id.info_replace_pc_steps,
                R.id.info_app_version, R.id.info_local_service,
                R.id.info_keep_screen_on, R.id.info_screen_timeout,
                R.id.info_cover_layout, R.id.info_forget_error,
                R.id.info_close, R.id.info_forget_pc
        };
        for (int id : values) typography.body(dialog.findViewById(id), typography.bodySp());
        JSONObject phone = snapshot == null ? null : snapshot.optJSONObject("phone");
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        String phoneModel = textField(phone, "model");
        setIfChanged(dialog.findViewById(R.id.info_phone_model),
                phoneModel.isEmpty() ? getString(R.string.info_unavailable)
                        : PhoneByline.modelAndMaker(phoneModel));
        updateInfoPcRows(dialog, gpu, pcConnection(gpu));
        String version = getString(R.string.info_unavailable);
        try {
            version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception ignored) {
            // Package metadata may be unavailable on a transient update.
        }
        if (version == null || version.isEmpty()) version = getString(R.string.info_unavailable);
        setIfChanged(dialog.findViewById(R.id.info_app_version), version);
        setIfChanged(dialog.findViewById(R.id.info_local_service), reachable
                ? getString(R.string.info_service_running)
                : getString(R.string.info_service_unavailable));
        ScreenTimeoutPreflight.Result timeout = ScreenTimeoutPreflight.assess(
                Settings.System.getInt(getContentResolver(), Settings.System.SCREEN_OFF_TIMEOUT, -1));
        setIfChanged(dialog.findViewById(R.id.info_screen_timeout),
                !timeout.known ? getString(R.string.info_screen_timeout_unknown)
                        : timeout.shorterThanTenMinutes
                        ? getString(R.string.info_screen_timeout_short, timeout.duration)
                        : getString(R.string.info_screen_timeout_value, timeout.duration));
        View forgetPc = dialog.findViewById(R.id.info_forget_pc);
        forgetPc.setOnClickListener(view -> showForgetConfirmation(dialog));
        dialog.findViewById(R.id.info_close).setOnClickListener(view -> dialog.dismiss());
        Window window = dialog.getWindow();
        if (window != null) window.setWindowAnimations(0);
        dialog.show();
        if (window != null) {
            window.setLayout(WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT);
        }
    }

    private String trustedPcLabel() {
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        if (!reachable || link == null || link.optJSONObject("pc") == null) return null;
        String label = pcLabel(gpu);
        return label.isEmpty() ? pcWords(R.string.pc) : label;
    }

    private String trustedPcFingerprint() {
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        return !reachable || link == null ? "" : pcFingerprint(link.optJSONObject("pc"));
    }

    private static String pcFingerprint(JSONObject pc) {
        if (pc == null) return "";
        String id = pc.optString("id", "");
        return PcFingerprint.normalized(id);
    }

    private boolean sameTrustedPc(String label, String fingerprint) {
        return ForgetAction.canConfirm(label, fingerprint,
                trustedPcLabel(), trustedPcFingerprint());
    }

    private void showForgetConfirmation(Dialog info) {
        // Capture the exact identifier visible in Settings. A later snapshot must not
        // replace the fingerprint attached to this confirmed request.
        String label = ((TextView) info.findViewById(R.id.info_pc)).getText().toString();
        String fingerprint = PcFingerprint.normalized(
                ((TextView) info.findViewById(R.id.info_pc_id)).getText().toString());
        if (label.isEmpty() || acting || !info.isShowing()) return;
        setIfChanged(info.findViewById(R.id.info_forget_error), "");
        showAlert(new AlertDialog.Builder(this, R.style.LinkDialogTheme)
                .setTitle(pcWords(R.string.forget_pc_title))
                .setMessage(pcWords(R.string.forget_pc_first_message))
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.continue_label, (first, which) -> {
                    if (!sameTrustedPc(label, fingerprint)) {
                        setIfChanged(info.findViewById(R.id.info_forget_error),
                                pcWords(R.string.forget_pc_changed));
                        return;
                    }
                    showAlert(new AlertDialog.Builder(this, R.style.LinkDialogTheme)
                            .setTitle(pcWords(R.string.forget_pc_confirm_title))
                            .setMessage(pcWords(R.string.forget_pc_second_message, label))
                            .setNegativeButton(R.string.cancel, null)
                            .setPositiveButton(pcWords(R.string.forget_pc_final), (second, confirmed) -> {
                                if (acting) return;
                                if (!sameTrustedPc(label, fingerprint)) {
                                    setIfChanged(info.findViewById(R.id.info_forget_error),
                                            pcWords(R.string.forget_pc_changed));
                                    return;
                                }
                                postForget(info, fingerprint);
                            }));
                }));
    }

    private void postForget(Dialog info, String shownPcId) {
        if (!visible || !reachable || acting || !info.isShowing()) return;
        JSONObject body = new JSONObject(ForgetAction.body(shownPcId));
        acting = true;
        handler.removeCallbacks(poll);
        info.findViewById(R.id.info_forget_pc).setEnabled(false);
        setIfChanged(info.findViewById(R.id.info_forget_error), "");
        updateButtons();
        network.execute(() -> {
            try {
                JSONObject updated = client.post(body);
                handler.post(() -> {
                    acting = false;
                    if (!visible) return;
                    reachable = true;
                    showSnapshot(updated);
                    schedule(0);
                });
            } catch (IOException | JSONException failure) {
                handler.post(() -> {
                    acting = false;
                    if (!visible) return;
                    String message = failure instanceof AiClient.ApiException
                            ? failure.getMessage() : getString(R.string.action_failed);
                    if (info.isShowing()) {
                        setIfChanged(info.findViewById(R.id.info_forget_error), message);
                        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
                        updateInfoPcRows(info, gpu, pcConnection(gpu));
                    } else setIfChanged(error, message);
                    updateButtons();
                    schedule(2000);
                });
            }
        });
    }

    private static String pcLabel(JSONObject gpu) {
        if (gpu == null) return "";
        JSONObject link = gpu.optJSONObject("link");
        JSONObject pc = link == null ? null : link.optJSONObject("pc");
        String label = computerLabel(pc);
        if (!label.isEmpty()) return label;
        JSONObject pending = link == null ? null : link.optJSONObject("pending");
        label = computerLabel(pending);
        if (!label.isEmpty()) return label;
        label = gpu.optString("where").trim();
        return "unknown".equalsIgnoreCase(label) ? "" : label;
    }

    private int themeColor(int resId) {
        if (resId == R.color.newspaper_paper) return parseHex(palette.paper());
        if (resId == R.color.newspaper_ink) return parseHex(palette.ink());
        if (resId == R.color.newspaper_stroke) return parseHex(palette.stroke());
        if (resId == R.color.you_asked_label) return parseHex(palette.label());
        if (resId == R.color.notes_rule) return parseHex(palette.notesRule());
        if (resId == R.color.newspaper_error) return parseHex(palette.error());
        if (resId == R.color.newspaper_ok) return parseHex(palette.ok());
        return getColor(resId);
    }

    private static int parseHex(String hex) {
        return UiPalette.argb(hex);
    }

    private boolean systemDark() {
        int night = getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return night != Configuration.UI_MODE_NIGHT_NO;
    }

    private void applyUi() {
        typography.useChoice(uiSettings.typography());
        typography.useCover(coverMode);
        palette = uiSettings.palette(systemDark());
        applyPaletteToPage();
        applyTypographyToPage();
        applyErrorView();
        showHeat(heatStatus); // the meter's heat color follows the new theme
        JSONObject gpu = snapshot == null ? null : snapshot.optJSONObject("gpu");
        renderLinkBanner(pcConnection(gpu) == Connection.CONNECTED, hasVisiblePcWork());
    }

    private void applySystemBars() {
        Window window = getWindow();
        int paper = themeColor(R.color.newspaper_paper);
        window.setStatusBarColor(paper);
        window.setNavigationBarColor(paper);
        if (Build.VERSION.SDK_INT >= 30) {
            android.view.WindowInsetsController controller = window.getInsetsController();
            if (controller != null) {
                int light = android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                controller.setSystemBarsAppearance(palette.light() ? light : 0, light);
            }
        } else {
            View decor = window.getDecorView();
            int flags = decor.getSystemUiVisibility();
            int lightFlags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= 26) {
                lightFlags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            decor.setSystemUiVisibility(palette.light() ? flags | lightFlags : flags & ~lightFlags);
        }
    }

    private GradientDrawable panelDrawable(String strokeHex) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(themeColor(R.color.newspaper_paper));
        drawable.setStroke(cardStrokePx(), parseHex(strokeHex));
        return drawable;
    }

    private int cardStrokePx() {
        float width = LaneCardLayout.STROKE_DP * getResources().getDisplayMetrics().density;
        return Math.max(1, Math.round(width));
    }

    private void applyCardStroke(View card, UiPalette.Tone tone) {
        if (card != null) card.setBackground(panelDrawable(palette.cardStroke(tone)));
    }

    private void applyTone(TextView view) {
        if (view == null) return;
        UiPalette.Tone tone = UiPalette.tone(view.getText());
        boolean paused = tone == UiPalette.Tone.PAUSED;
        Object saved = view.getTag(R.id.paused_chip);
        if (paused && !(saved instanceof PausedChip)) {
            // A paused line is an inverted chip (paper on ink), readable from the back row.
            // The view's own padding and background come back when the pause ends.
            view.setTag(R.id.paused_chip, new PausedChip(view));
            view.setPadding(view.getPaddingLeft() + dp(6), view.getPaddingTop(),
                    view.getPaddingRight() + dp(6), view.getPaddingBottom());
        } else if (!paused && saved instanceof PausedChip) {
            ((PausedChip) saved).restore(view);
            view.setTag(R.id.paused_chip, null);
        }
        if (paused) {
            int ink = parseHex(palette.ink());
            if (!(view.getBackground() instanceof android.graphics.drawable.ColorDrawable)
                    || ((android.graphics.drawable.ColorDrawable) view.getBackground()).getColor() != ink) {
                view.setBackgroundColor(ink);
            }
        }
        view.setTextColor(parseHex(paused ? palette.paper() : palette.colorForTone(tone)));
    }

    /** What a status view looked like before it became a paused chip. */
    private static final class PausedChip {
        final int left, top, right, bottom;
        /** Status lines have no background of their own today; any other is kept as is. */
        final android.graphics.drawable.Drawable background;

        PausedChip(TextView view) {
            left = view.getPaddingLeft();
            top = view.getPaddingTop();
            right = view.getPaddingRight();
            bottom = view.getPaddingBottom();
            background = view.getBackground();
        }

        void restore(TextView view) {
            // Background first: a drawable with its own padding would overwrite ours.
            view.setBackground(background);
            view.setPadding(left, top, right, bottom);
        }
    }

    private void applyErrorView() {
        if (error == null) return;
        syncErrorVisibility();
        boolean has = error.getText() != null && error.getText().length() > 0;
        error.setTextColor(parseHex(has ? palette.error() : palette.ink()));
    }

    private void styleErrorButton(Button button, boolean errorState) {
        if (button == null) return;
        styleButton(button, parseHex(errorState ? palette.error() : palette.ink()),
                panelDrawable(errorState ? palette.error() : palette.stroke()));
    }

    private void styleLaneRetry(Button button, LaneHealth.Verdict verdict) {
        UiPalette.Tone tone = UiPalette.toneFromStatus(
                verdict.status == null ? "" : verdict.status.name(), verdict.garbled);
        styleErrorButton(button, UiPalette.retryAppliesToError(tone));
    }

    private void applyPaletteToPage() {
        applySystemBars();
        int paper = themeColor(R.color.newspaper_paper);
        int ink = themeColor(R.color.newspaper_ink);
        int label = themeColor(R.color.you_asked_label);
        if (screen != null) screen.setBackgroundColor(paper);
        recolorChrome(screen, paper, ink, label);
        if (pairing != null) {
            pairing.setBackgroundColor(paper);
            recolorChrome(pairing, paper, ink, label);
            applyPairingCountdownTone();
        }
        if (notes != null) {
            notes.setTextColor(ink);
            notes.setHintTextColor(label);
            notes.setBackgroundColor(paper);
            notes.setRuleColor(themeColor(R.color.notes_rule));
        }
        if (notesCard != null && !notesDragActive) {
            notesCard.setBackground(panelDrawable(palette.stroke()));
        }
        styleDeviceBand();
        styleNotesDock();
        syncErrorVisibility();
        if (timingCard != null) timingCard.setBackground(panelDrawable(palette.stroke()));
        if (summaryCard != null) summaryCard.setBackground(panelDrawable(palette.stroke()));
        if (bottomDock != null) {
            recolorChrome(bottomDock,
                    themeColor(R.color.newspaper_paper),
                    themeColor(R.color.newspaper_ink),
                    themeColor(R.color.you_asked_label));
        }
        if (summaryText != null) {
            setSummaryReport(summaryText.getText().toString());
        }
        if (tonightRows != null && tonightTiming != null) {
            fillTonightRows(tonightRows, tonightTiming.getText().toString(), tonightLanes);
        }
        if (notesTab != null) styleNotesDock();
        for (PaneViews pane : paneViews.values()) {
            applyCardStroke(pane.card, UiPalette.tone(pane.state.getText()));
            applyTone(pane.state);
            applyTone(pane.kicker);
        }
        applyTone(status);
        if (tonightProvenance != null) applyTone(tonightProvenance);
        applyErrorView();
        styleErrorButton(retry, retry != null && retry.getVisibility() == View.VISIBLE);
        if (send != null) stylePrimaryButton(send);
        if (prompt != null) {
            prompt.setBackground(panelDrawable(palette.stroke()));
            prompt.setHintTextColor(themeColor(R.color.you_asked_label));
            prompt.setTextColor(themeColor(R.color.newspaper_ink));
        }
        LinearLayout composer = findViewById(R.id.composer);
        LinearLayout row = findViewById(R.id.input_row);
        if (composer != null) composer.setBackgroundColor(themeColor(R.color.newspaper_paper));
        if (row != null) row.setBackgroundColor(themeColor(R.color.newspaper_paper));
        if (info != null) styleChromeOutline(info);
        if (settings != null) styleChromeOutline(settings);
        if (settingsDialog != null && settingsDialog.isShowing()) applyPaletteToDialog(settingsDialog);
        if (infoDialog != null && infoDialog.isShowing()) applyPaletteToDialog(infoDialog);
        if (summaryDialog != null && summaryDialog.isShowing()) applyPaletteToDialog(summaryDialog);
    }

    private void stylePrimaryButton(Button button) {
        GradientDrawable fill = new GradientDrawable();
        fill.setColor(themeColor(R.color.newspaper_ink));
        styleButton(button, themeColor(R.color.newspaper_paper), fill);
    }

    private void styleChromeOutline(Button button) {
        styleButton(button, themeColor(R.color.newspaper_ink), panelDrawable(palette.stroke()));
    }

    private void styleButton(Button button, int enabledText, GradientDrawable enabledBackground) {
        int[] disabled = {-android.R.attr.state_enabled};
        int[] enabled = {android.R.attr.state_enabled};
        button.setTextColor(new ColorStateList(new int[][]{disabled, enabled},
                new int[]{parseHex(palette.label()), enabledText}));
        GradientDrawable disabledBackground = panelDrawable(palette.stroke());
        disabledBackground.setAlpha(120);
        StateListDrawable backgrounds = new StateListDrawable();
        backgrounds.addState(disabled, disabledBackground);
        backgrounds.addState(enabled, enabledBackground);
        button.setBackground(backgrounds);
    }

    private void recolorChrome(View view, int paper, int ink, int label) {
        if (view == null) return;
        if (view == send || view == reconnect || view == allow || view == reopen) {
            stylePrimaryButton((Button) view);
            return;
        }
        if (view instanceof Button) {
            Button button = (Button) view;
            if (button == retry) {
                styleErrorButton(retry, retry.getVisibility() == View.VISIBLE);
                return;
            }
            styleChromeOutline(button);
            return;
        }
        if (view instanceof EditText) {
            EditText edit = (EditText) view;
            if (view != notes) {
                edit.setTextColor(ink);
                edit.setHintTextColor(label);
            }
            return;
        }
        if (view == notesTabLabel) {
            notesTabLabel.setTextColor(notesConfirming
                    ? parseHex(palette.ok())
                    : themeColor(R.color.you_asked_label));
            return;
        }
        if (view instanceof TextView
                && view != status && view != error && view != tonightProvenance
                && view != pairingCountdown
                && (paneViews == null || !isPaneStateOrKicker(view))) {
            ((TextView) view).setTextColor(ink);
        }
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                recolorChrome(group.getChildAt(i), paper, ink, label);
            }
        }
    }

    private boolean isPaneStateOrKicker(View view) {
        for (PaneViews pane : paneViews.values()) {
            if (view == pane.state || view == pane.kicker) return true;
        }
        return false;
    }

    private void applyPaletteToDialog(Dialog dialog) {
        if (dialog == null || dialog.getWindow() == null) return;
        dialog.getWindow().setBackgroundDrawable(new ColorDrawable(themeColor(R.color.newspaper_paper)));
        dialog.getWindow().setStatusBarColor(themeColor(R.color.newspaper_paper));
        dialog.getWindow().setNavigationBarColor(themeColor(R.color.newspaper_paper));
        recolorChrome(dialog.getWindow().getDecorView(),
                themeColor(R.color.newspaper_paper),
                themeColor(R.color.newspaper_ink),
                themeColor(R.color.you_asked_label));
    }

    private void applyTypographyToPage() {
        typography.useChoice(uiSettings.typography());
        typography.useCover(coverMode);
        applyPairingTypography();
        if (deviceBand != null) {
            typography.kicker(devicePhoneKicker);
            typography.kicker(deviceComputerKicker);
            typography.headline(devicePhoneName, typography.headingSp());
            typography.headline(deviceComputerName, typography.headingSp());
            typography.state(deviceLink);
            deviceLink.setFontFeatureSettings(null);
        }
        if (bigMasthead != null) {
            typography.display(bigMasthead, coverMode ? CoverScreenPolicy.MASTHEAD_SP : 34);
        }
        if (question != null) applyQuestionLayout(question);
        if (notesTabLabel != null) typography.kicker(notesTabLabel);
        if (summaryHeading != null) typography.headline(summaryHeading, typography.headingSp());
        if (summaryText != null) setSummaryReport(summaryText.getText().toString());
        for (PaneViews pane : paneViews.values()) {
            typography.headline(pane.heading, typography.headingSp());
            typography.kicker(pane.kicker);
            typography.byline(pane.byline);
            typography.state(pane.state);
            typography.tabular(pane.state);
            typography.state(pane.speed);
            typography.body(pane.answer, typography.bodySp());
            if (pane.working != null) {
                typography.state(pane.working);
                typography.state(pane.workingCount);
                pane.workingSpans.line = "";
                updateWorking(pane);
            }
        }
        if (tonightRows != null && tonightTiming != null) {
            fillTonightRows(tonightRows, tonightTiming.getText().toString(), tonightLanes);
        }
        if (notes != null) typography.body(notes, typography.bodySp());
        if (settingsDialog != null && settingsDialog.isShowing()) {
            typography.defaults(settingsDialog.getWindow().getDecorView());
        }
    }

    private void showSettings() {
        if (settingsDialog != null && settingsDialog.isShowing()) return;
        Dialog dialog = new Dialog(this, R.style.InfoDialogTheme);
        settingsDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (settingsDialog == dialog) {
                settingsDialog = null;
                settingsLabList = null;
            }
        });
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(true);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        int pagePad = dp(coverMode ? 10 : 16);
        page.setPadding(pagePad, pagePad, pagePad, pagePad);
        page.setBackgroundColor(themeColor(R.color.newspaper_paper));
        page.addView(pageBar(getString(R.string.settings), getString(R.string.close),
                view -> dialog.dismiss()));
        TextView section = newspaperText(getString(R.string.settings_ui), typography.labelSp(), true, false);
        typography.kicker(section);
        section.setPadding(0, dp(coverMode ? 8 : 16), 0, dp(coverMode ? 4 : 8));
        page.addView(section);
        // Theme first so Dark / Light / Follow system are on-screen on a 720x748 cover.
        TextView themeHeading = newspaperText(getString(R.string.settings_theme),
                typography.headingSp(), true, true);
        typography.headline(themeHeading, typography.headingSp());
        themeHeading.setPadding(0, dp(coverMode ? 4 : 8), 0, dp(coverMode ? 4 : 8));
        page.addView(themeHeading);
        LinearLayout themeList = new LinearLayout(this);
        themeList.setOrientation(LinearLayout.VERTICAL);
        page.addView(themeList);
        TextView labHeading = newspaperText(getString(R.string.settings_design_lab),
                typography.headingSp(), true, true);
        typography.headline(labHeading, typography.headingSp());
        labHeading.setPadding(0, dp(16), 0, dp(4));
        TextView labNote = newspaperText(getString(R.string.settings_design_lab_note),
                typography.labelSp(), false, false);
        labNote.setTextColor(themeColor(R.color.you_asked_label));
        LinearLayout labList = new LinearLayout(this);
        labList.setOrientation(LinearLayout.VERTICAL);
        if (!coverMode) {
            page.addView(labHeading);
            page.addView(labNote);
            page.addView(labList);
            settingsLabList = labList;
            bindDesignLabList(labList);
        }
        scroll.addView(page);
        // Keep the Settings title below the status bar (same as the Info sheet).
        padForSystemBars(scroll);
        dialog.setContentView(scroll);
        bindSettingsLists(themeList);
        applyPaletteToDialog(dialog);
        Window window = dialog.getWindow();
        if (window != null) window.setWindowAnimations(0);
        dialog.show();
        if (window != null) {
            window.setLayout(WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT);
        }
    }

    private void bindSettingsLists(LinearLayout themeList) {
        themeList.removeAllViews();
        String currentTheme = uiSettings.themePreference();
        String[] themes = {UiSettings.THEME_DARK, UiSettings.THEME_LIGHT, UiSettings.THEME_SYSTEM};
        for (String id : themes) {
            boolean selected = id.equals(currentTheme);
            LinearLayout row = optionRow(UiSettings.themeCaption(id), "", selected);
            final String choice = id;
            row.setOnClickListener(view -> {
                if (!uiSettings.setTheme(choice)) return;
                applyUi();
                updateOptionRows(themeList, themes, choice);
                view.sendAccessibilityEvent(
                        android.view.accessibility.AccessibilityEvent.TYPE_VIEW_SELECTED);
            });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            params.topMargin = dp(coverMode ? 4 : 6);
            themeList.addView(row, params);
        }
    }

    private void bindDesignLabList(LinearLayout labList) {
        labList.removeAllViews();
        String current = uiSettings.designLab();
        for (String id : DesignLab.MODES) {
            LinearLayout row = optionRow(DesignLab.caption(id), "", id.equals(current));
            final String choice = id;
            row.setOnClickListener(view -> {
                if (!uiSettings.setDesignLab(choice)) return;
                arrangeArticles();
                updateOptionRows(labList, DesignLab.MODES.toArray(new String[0]), choice);
                view.sendAccessibilityEvent(
                        android.view.accessibility.AccessibilityEvent.TYPE_VIEW_SELECTED);
            });
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            params.topMargin = dp(coverMode ? 4 : 6);
            labList.addView(row, params);
        }
    }

    private LinearLayout optionRow(String title, String caption, boolean selected) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(coverMode ? 6 : 10);
        row.setPadding(pad, pad, pad, pad);
        row.setMinimumHeight(dp(48));
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView heading = newspaperText(title, typography.labelSp() + 2, true, false);
        heading.setTextColor(themeColor(R.color.newspaper_ink));
        row.addView(heading);
        TextView sub = newspaperText("", typography.labelSp(), false, false);
        sub.setTextColor(themeColor(R.color.you_asked_label));
        sub.setPadding(0, dp(2), 0, 0);
        row.addView(sub);
        setOptionSelected(row, caption, selected);
        row.setClickable(true);
        row.setFocusable(true);
        // TalkBack reads each choice as a radio button, checked or not checked.
        row.setAccessibilityDelegate(new View.AccessibilityDelegate() {
            @Override
            public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(RadioButton.class.getName());
                info.setCheckable(true);
                info.setChecked(host.isSelected());
            }
        });
        return row;
    }

    private void setOptionSelected(LinearLayout row, String caption, boolean selected) {
        row.setSelected(selected);
        row.setBackground(panelDrawable(selected ? palette.ink() : palette.stroke()));
        TextView sub = (TextView) row.getChildAt(1);
        String detail = selected ? getString(R.string.settings_selected)
                + (caption.isEmpty() ? "" : " · " + caption) : caption;
        setIfChanged(sub, detail);
        sub.setVisibility(detail.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void updateOptionRows(LinearLayout list, String[] ids, String selected) {
        for (int i = 0; i < ids.length && i < list.getChildCount(); i++) {
            setOptionSelected((LinearLayout) list.getChildAt(i), "", ids[i].equals(selected));
        }
    }

    /** Reserve the Notes tab height at the bottom of the results so Summary is not covered. */
    private void applyResultsContentPadding() {
        View content = findViewById(R.id.content);
        int notesH = 0;
        int summaryH = 0;
        if (notesDock != null && notesDock.getVisibility() == View.VISIBLE) {
            notesH = notesDock.getHeight();
            if (notesH <= 0) notesH = currentNotesSheetHeight();
        }
        if (summaryCard != null && summaryCard.getVisibility() == View.VISIBLE
                && bottomDock != null && summaryCard.getParent() == bottomDock) {
            summaryH = cappedSummaryHeight(summaryCard.getHeight());
        }
        int bottom = NotesSheet.contentBottomPad(notesH, summaryH, collapsedDockReserve());
        if (content != null) {
            content.setPadding(dp(12), dp(4), dp(12), bottom);
        }
        if (resultsScroll != null) {
            resultsScroll.setClipToPadding(true);
            resultsScroll.setPadding(resultsScroll.getPaddingLeft(), resultsScroll.getPaddingTop(),
                    resultsScroll.getPaddingRight(), 0);
        }
        applyScreenBottomReserve();
    }

    /** Keep the Ask box and results above the collapsed Notes tab + Summary bar. */
    private int summaryCapPx() {
        return dp(NotesSheet.summaryMaxDp(coverMode, landscapeLayout, summaryExpanded));
    }

    private int summaryMinPx() {
        return dp(NotesSheet.summaryMinDp(landscapeLayout));
    }

    private int cappedSummaryHeight(int measured) {
        if (landscapeLayout) return summaryCapPx();
        return NotesSheet.summaryHeight(measured, summaryMinPx(), summaryCapPx());
    }

    private int collapsedDockReserve() {
        if (bottomDock == null || bottomDock.getVisibility() != View.VISIBLE) return 0;
        int summaryH = 0;
        if (summaryCard != null && summaryCard.getVisibility() == View.VISIBLE
                && summaryCard.getParent() == bottomDock) {
            summaryH = cappedSummaryHeight(summaryCard.getHeight());
        } else {
            summaryH = summaryMinPx();
        }
        return notesCollapsedH() + summaryH;
    }

    private void applyScreenBottomReserve() {
        if (screen == null) return;
        int reserve = collapsedDockReserve();
        screen.setPadding(insetLeft, insetTop, insetRight, insetBottom + reserve);
        applyBottomDockInsets(insetLeft, insetRight, insetBottom);
    }

    private void setSummaryHeadingCue(boolean expanded) {
        String title = "SUMMARY";
        String cue = expanded ? " · Close" : " · Open";
        SpannableStringBuilder heading = new SpannableStringBuilder(title + cue);
        heading.setSpan(new TypefaceSpan(typography.interMedium), title.length(), heading.length(),
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        int cuePx = Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP,
                typography.labelSp(), getResources().getDisplayMetrics()));
        heading.setSpan(new AbsoluteSizeSpan(cuePx, false), title.length(),
                heading.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        summaryHeading.setText(heading);
        summaryHeading.setContentDescription(getString(expanded
                ? R.string.summary_close : R.string.summary_open));
    }

    private void pinSummaryBar() {
        if (summaryCard == null) return;
        if (bottomDock == null) {
            FrameLayout stage = findViewById(R.id.results_stage);
            if (stage == null) return;
            setupNotesDock();
        }
        if (bottomDock == null) return;
        summaryCard.setLayoutTransition(null);
        summaryCard.animate().cancel();
        summaryCard.setAlpha(1f);
        summaryCard.setTranslationY(0f);
        summaryCard.setMinimumHeight(summaryMinPx());
        int summaryVerticalPad = dp(landscapeLayout ? 4 : LaneCardLayout.CARD_PADDING_DP);
        summaryCard.setPadding(dp(LaneCardLayout.CARD_PADDING_DP), summaryVerticalPad,
                dp(LaneCardLayout.CARD_PADDING_DP), summaryVerticalPad);
        if (landscapeLayout) {
            summaryCard.setPadding(dp(LaneCardLayout.CARD_PADDING_DP), 0,
                    dp(LaneCardLayout.CARD_PADDING_DP), 0);
            if (summaryRow == null) {
                summaryRow = new LinearLayout(this);
                summaryRow.setOrientation(LinearLayout.HORIZONTAL);
                summaryRow.setGravity(Gravity.CENTER_VERTICAL);
                detach(summaryHeading);
                summaryCard.addView(summaryRow, 0, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, dp(NotesSheet.SUMMARY_WIDE_DP)));
                summaryRow.addView(summaryHeading, new LinearLayout.LayoutParams(0,
                        LinearLayout.LayoutParams.MATCH_PARENT, 1f));
                detach(summaryText);
                summaryScroll = new ScrollView(this);
                summaryScroll.setVerticalScrollBarEnabled(true);
                summaryScroll.setPadding(0, 0, dp(8), dp(8));
                summaryScroll.addView(summaryText, new ScrollView.LayoutParams(
                        ScrollView.LayoutParams.MATCH_PARENT,
                        ScrollView.LayoutParams.WRAP_CONTENT));
                summaryCard.addView(summaryScroll, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        0, 1f));
                summaryHeading.setGravity(Gravity.CENTER_VERTICAL);
                summaryHeading.setSingleLine(true);
                summaryHeading.setEllipsize(TextUtils.TruncateAt.END);
                summaryHeading.setFocusable(true);
                summaryHeading.setAccessibilityDelegate(mastheadButtonRole());
                summaryHeading.setOnClickListener(view -> {
                    if (!summaryExpanded && notesSheetState != NotesSheet.State.COLLAPSED) {
                        setNotesSheetState(NotesSheet.State.COLLAPSED, false);
                    }
                    summaryExpanded = !summaryExpanded;
                    pinSummaryBar();
                    setNotesSheetState(notesSheetState, false);
                });
                LinearLayout tabRow = (LinearLayout) notesTab.getParent();
                tabRow.setVisibility(View.GONE);
                detach(notesTab);
                notesTab.setPadding(dp(12), 0, dp(12), 0);
                notesTab.setMinimumWidth(dp(48));
                summaryRow.addView(notesTab, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.WRAP_CONTENT, dp(NotesSheet.SUMMARY_WIDE_DP)));
                notes.setAccessibilityTraversalAfter(notesTab.getId());
            }
            setSummaryHeadingCue(summaryExpanded);
            summaryScroll.setVisibility(summaryExpanded ? View.VISIBLE : View.GONE);
        } else if (NotesSheet.summaryOpensFullPage(landscapeLayout)) {
            summaryCard.setClickable(true);
            summaryCard.setFocusable(false);
            // Keep the preview readable on its own after the open action.
            summaryCard.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            summaryCard.setOnClickListener(view -> showSummaryPage());
            summaryHeading.setFocusable(true);
            summaryHeading.setMinimumHeight(dp(coverMode ? 0 : 48));
            summaryHeading.setGravity(Gravity.CENTER_VERTICAL);
            setSummaryHeadingCue(false);
            summaryHeading.setAccessibilityDelegate(mastheadButtonRole());
            summaryHeading.setOnClickListener(view -> showSummaryPage());
        }
        if (summaryText != null) {
            if (landscapeLayout) {
                summaryText.setMaxLines(Integer.MAX_VALUE);
                summaryText.setEllipsize(null);
            } else {
                summaryText.setMaxLines(coverMode ? 3 : 8);
                summaryText.setEllipsize(android.text.TextUtils.TruncateAt.END);
                summaryText.setMaxHeight(summaryCapPx());
            }
        }
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                summaryCapPx());
        if (landscapeLayout && summaryCard.getParent() == bottomDock) {
            summaryCard.setLayoutParams(params);
        } else {
            detach(summaryCard);
            bottomDock.addView(summaryCard, params);
        }
        summaryCard.setVisibility(View.VISIBLE);
        bottomDock.setVisibility(View.VISIBLE);
        bottomDock.bringToFront();
        applyResultsContentPadding();
    }

    private void setupNotesDock() {
        FrameLayout stage = findViewById(R.id.results_stage);
        if (stage == null || notesCard == null) return;
        if (notesDock == null) {
            notesDock = new LinearLayout(this);
            notesDock.setOrientation(LinearLayout.VERTICAL);
            LinearLayout tabRow = new LinearLayout(this);
            tabRow.setOrientation(LinearLayout.HORIZONTAL);
            tabRow.setGravity(Gravity.CENTER_HORIZONTAL);
            notesTab = new LinearLayout(this);
            notesTab.setOrientation(LinearLayout.HORIZONTAL);
            notesTab.setGravity(Gravity.CENTER);
            notesTab.setPadding(dp(18), dp(8), dp(18), dp(6));
            notesTab.setClickable(true);
            notesTab.setFocusable(true);
            notesTab.setId(View.generateViewId());
            notesTab.setAccessibilityDelegate(mastheadButtonRole());
            notesTab.setOnClickListener(view -> setNotesSheetState(
                    NotesSheet.onTabTap(notesSheetState), true));
            notesTabLabel = newspaperText(NotesSheet.tabLabel(0), typography.labelSp(), true, false);
            typography.kicker(notesTabLabel);
            notesTab.addView(notesTabLabel);
            tabRow.addView(notesTab, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, dp(NotesSheet.TAB_DP)));
            // A clear strip above the tab makes it a 48 dp touch target without a bigger tab.
            tabRow.setPadding(0, dp(NotesSheet.TAB_SLOP_DP), 0, 0);
            tabRow.addOnLayoutChangeListener((view, l, t, r, b, ol, ot, or, ob) -> {
                Rect hit = new Rect();
                notesTab.getHitRect(hit);
                hit.top = 0;
                int need = Math.max(0, dp(48) - hit.width());
                hit.left -= need / 2;
                hit.right += need - need / 2;
                // Shift back inside the row instead of clipping, so the target stays 48 dp wide.
                if (hit.left < 0) hit.offset(-hit.left, 0);
                if (hit.right > r - l) hit.offset((r - l) - hit.right, 0);
                hit.left = Math.max(0, hit.left);
                view.setTouchDelegate(new TouchDelegate(hit, notesTab));
            });
            notesDock.addView(tabRow, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(NotesSheet.TAB_TOUCH_DP)));
            detach(notesCard);
            notesCard.setLayoutTransition(null);
            notesCard.setMinimumHeight(0);
            notesCard.setVisibility(View.VISIBLE);
            if (notes != null) {
                notesCard.removeView(notes);
                notesCard.addView(notes, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, 0));
            }
            notesDock.addView(notesCard, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, 0));
            bottomDock = new LinearLayout(this);
            bottomDock.setOrientation(LinearLayout.VERTICAL);
            FrameLayout.LayoutParams dockParams = new FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    Gravity.BOTTOM);
            bottomDock.addView(notesDock, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            notesOverlayHost().addView(bottomDock, dockParams);
            applyScreenBottomReserve();
            notesTab.setOnTouchListener(notesSheetTouchListener());
            notesTab.setOnDragListener(notesTargetListener());
            notesCard.setOnDragListener(notesTargetListener());
            stage.addOnLayoutChangeListener((view, left, top, right, bottom,
                    oldLeft, oldTop, oldRight, oldBottom) -> {
                if (notesSheetDragging) return;
                if (notesSpringCallback != null) return;
                if (notesSheetAnimator != null && notesSheetAnimator.isRunning()) return;
                if (bottom - top != oldBottom - oldTop) {
                    applyNotesSheetHeight(NotesSheet.height(notesSheetState,
                            notesCollapsedH(), notesHalfH(), notesFullH()));
                }
            });
            bottomDock.addOnLayoutChangeListener((view, left, top, right, bottom,
                    oldLeft, oldTop, oldRight, oldBottom) -> {
                if (bottom - top != oldBottom - oldTop) applyResultsContentPadding();
            });
        }
        boolean show = NotesSheet.available(coverMode);
        notesDock.setVisibility(show ? View.VISIBLE : View.GONE);
        if (bottomDock != null) bottomDock.setVisibility(View.VISIBLE);
        pinSummaryBar();
        applyResultsContentPadding();
        updateNotesTab();
        styleNotesDock();
        if (show) {
            applyNotesSheetHeight(NotesSheet.height(notesSheetState,
                    notesCollapsedH(), notesHalfH(), notesFullH()));
        }
    }

    private void styleNotesDock() {
        if (notesTab != null) {
            notesTab.setBackground(landscapeLayout
                    ? (notesDragActive ? panelDrawable(palette.ink()) : null)
                    : folderTabDrawable(notesDragActive));
        }
        if (notesCard != null && !notesDragActive) {
            notesCard.setBackground(panelDrawable(palette.stroke()));
        }
        if (notesTabLabel != null) {
            notesTabLabel.setTextColor(notesConfirming
                    ? parseHex(palette.ok())
                    : themeColor(R.color.you_asked_label));
        }
    }

    private GradientDrawable folderTabDrawable(boolean highlight) {
        GradientDrawable tab = new GradientDrawable();
        tab.setColor(themeColor(R.color.newspaper_paper));
        tab.setStroke(highlight ? dp(2) : cardStrokePx(),
                parseHex(highlight ? palette.ink() : palette.stroke()));
        float radius = dp(10);
        tab.setCornerRadii(new float[]{radius, radius, radius, radius, 0, 0, 0, 0});
        return tab;
    }

    private void updateNotesTab() {
        if (notesTabLabel == null) return;
        if (notesConfirming) {
            notesTabLabel.setText(getString(R.string.notes_saved));
            notesTabLabel.setTextColor(parseHex(palette.ok()));
        } else {
            int count = NotesSheet.noteCount(notes == null ? "" : notes.getText());
            notesTabLabel.setText(NotesSheet.tabLabel(count));
            notesTabLabel.setTextColor(themeColor(R.color.you_asked_label));
        }
        if (notesTab != null) {
            boolean open = notesSheetState != NotesSheet.State.COLLAPSED;
            notesTab.setContentDescription(getString(open
                    ? R.string.notes_tab_close : R.string.notes_tab_open));
        }
        styleNotesDock();
    }

    private void showNotesConfirmation() {
        if (notesTabLabel == null) return;
        notesConfirming = true;
        handler.removeCallbacks(hideNotesConfirmRunnable);
        updateNotesTab();
        handler.postDelayed(hideNotesConfirmRunnable, NotesSheet.CONFIRM_MS);
    }

    private final Runnable hideNotesConfirmRunnable = () -> {
        notesConfirming = false;
        updateNotesTab();
    };

    private int notesCollapsedH() {
        return dp(NotesSheet.collapsedTabHeightDp(landscapeLayout));
    }

    private ViewGroup notesOverlayHost() {
        if (screen != null && screen.getParent() instanceof FrameLayout) {
            return (ViewGroup) screen.getParent();
        }
        return findViewById(R.id.results_stage);
    }

    private void applyBottomDockInsets(int left, int right, int bottom) {
        if (bottomDock == null) return;
        ViewGroup.LayoutParams raw = bottomDock.getLayoutParams();
        if (!(raw instanceof ViewGroup.MarginLayoutParams)) return;
        ViewGroup.MarginLayoutParams lp = (ViewGroup.MarginLayoutParams) raw;
        lp.leftMargin = left;
        lp.rightMargin = right;
        lp.bottomMargin = bottom;
        bottomDock.setLayoutParams(lp);
    }

    private int notesSheetAvailable() {
        int available = 0;
        ViewGroup host = notesOverlayHost();
        int hostH = host != null ? host.getHeight() : 0;
        if (hostH <= 0 && screen != null) hostH = screen.getHeight();
        available = Math.max(0, hostH - insetTop - insetBottom);
        if (available <= 0 && screen != null) {
            // Before insets land, fall back to the laid-out screen height.
            available = Math.max(0, screen.getHeight());
        }
        int summaryH = 0;
        if (summaryCard != null && summaryCard.getVisibility() == View.VISIBLE
                && bottomDock != null && summaryCard.getParent() == bottomDock) {
            summaryH = cappedSummaryHeight(summaryCard.getHeight());
        } else {
            summaryH = summaryMinPx();
        }
        return Math.max(notesCollapsedH(), available - summaryH);
    }

    private int notesHalfH() {
        return NotesSheet.halfHeight(notesSheetAvailable(), notesCollapsedH());
    }

    private int notesFullH() {
        return NotesSheet.fullHeight(notesSheetAvailable(), notesCollapsedH());
    }

    private int currentNotesSheetHeight() {
        if (notesCard == null || notesCard.getLayoutParams() == null) return notesCollapsedH();
        return notesCollapsedH() + Math.max(0, notesCard.getLayoutParams().height);
    }

    private void applyNotesSheetHeight(int total) {
        if (notesCard == null) return;
        int body = Math.max(0, total - notesCollapsedH());
        ViewGroup.LayoutParams params = notesCard.getLayoutParams();
        if (params == null) return;
        params.width = ViewGroup.LayoutParams.MATCH_PARENT;
        params.height = body;
        notesCard.setLayoutParams(params);
        notesCard.setVisibility(View.VISIBLE);
        notesCard.setAlpha(1f);
        notesCard.setBackground(panelDrawable(palette.stroke()));
        if (notes != null) {
            ViewGroup.LayoutParams editorParams = notes.getLayoutParams();
            if (editorParams == null) {
                editorParams = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        body > 0 ? LinearLayout.LayoutParams.MATCH_PARENT : 0);
                notes.setLayoutParams(editorParams);
            } else {
                editorParams.width = ViewGroup.LayoutParams.MATCH_PARENT;
                editorParams.height = body > 0 ? ViewGroup.LayoutParams.MATCH_PARENT : 0;
                notes.setLayoutParams(editorParams);
            }
            notes.setVisibility(View.VISIBLE);
            notes.setMinHeight(0);
            notes.setBackgroundColor(themeColor(R.color.newspaper_paper));
        }
        if (bottomDock != null) {
            bottomDock.bringToFront();
            bottomDock.requestLayout();
        } else if (notesDock != null) {
            notesDock.bringToFront();
            notesDock.requestLayout();
        }
        notesCard.requestLayout();
        notesCard.invalidate();
        applyResultsContentPadding();
    }

    private void cancelNotesSheetMotion() {
        if (notesSheetAnimator != null) {
            notesSheetAnimator.cancel();
            notesSheetAnimator = null;
        }
        if (notesSpringCallback != null) {
            Choreographer.getInstance().removeFrameCallback(notesSpringCallback);
            notesSpringCallback = null;
        }
    }

    private void setNotesSheetState(NotesSheet.State state, boolean animate) {
        setNotesSheetState(state, animate, 0f);
    }

    private void setNotesSheetState(NotesSheet.State state, boolean animate, float velocityPxPerSec) {
        if (landscapeLayout && state != NotesSheet.State.COLLAPSED && summaryExpanded) {
            summaryExpanded = false;
            pinSummaryBar();
        }
        notesSheetState = state;
        int target = NotesSheet.height(state, notesCollapsedH(), notesHalfH(), notesFullH());
        cancelNotesSheetMotion();
        if (!animate || reduceMotionEnabled) {
            applyNotesSheetHeight(target);
            updateNotesTab();
            return;
        }
        startNotesSpring(target, velocityPxPerSec);
        updateNotesTab();
    }

    private void startNotesSpring(int target, float velocityPxPerSec) {
        notesSpringPos = currentNotesSheetHeight();
        notesSpringVel = velocityPxPerSec;
        notesSpringTarget = target;
        notesSpringLastFrameNs = 0L;
        notesSpringCallback = frameTimeNs -> {
            if (notesSpringCallback == null) return;
            if (notesSpringLastFrameNs == 0L) {
                notesSpringLastFrameNs = frameTimeNs;
                Choreographer.getInstance().postFrameCallback(notesSpringCallback);
                return;
            }
            float dt = (frameTimeNs - notesSpringLastFrameNs) / 1_000_000_000f;
            notesSpringLastFrameNs = frameTimeNs;
            if (dt <= 0f) dt = 1f / 60f;
            if (dt > 0.064f) dt = 0.064f;
            NotesSpring.Step step = NotesSpring.step(
                    notesSpringPos, notesSpringVel, notesSpringTarget, dt);
            notesSpringPos = step.position;
            notesSpringVel = step.velocity;
            int low = notesCollapsedH();
            int high = notesFullH() + dp(NotesSpring.OVERSHOOT_DP);
            int height = Math.round(Math.max(low, Math.min(high, notesSpringPos)));
            applyNotesSheetHeight(height);
            if (step.settled) {
                applyNotesSheetHeight(Math.round(notesSpringTarget));
                notesSpringCallback = null;
                updateNotesTab();
                return;
            }
            Choreographer.getInstance().postFrameCallback(notesSpringCallback);
        };
        Choreographer.getInstance().postFrameCallback(notesSpringCallback);
    }

    private View.OnTouchListener notesSheetTouchListener() {
        return (view, event) -> {
            if (!NotesSheet.available(coverMode)) return false;
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    notesSheetDragging = false;
                    notesSheetDownY = event.getRawY();
                    notesSheetStartHeight = currentNotesSheetHeight();
                    if (notesSheetVelocity != null) notesSheetVelocity.recycle();
                    notesSheetVelocity = VelocityTracker.obtain();
                    notesSheetVelocity.addMovement(event);
                    if (view.getParent() != null) {
                        view.getParent().requestDisallowInterceptTouchEvent(true);
                    }
                    return true;
                case MotionEvent.ACTION_MOVE:
                    if (notesSheetVelocity != null) notesSheetVelocity.addMovement(event);
                    float dy = event.getRawY() - notesSheetDownY;
                    if (!notesSheetDragging && Math.abs(dy)
                            > ViewConfiguration.get(this).getScaledTouchSlop()) {
                        notesSheetDragging = true;
                        cancelNotesSheetMotion();
                    }
                    if (notesSheetDragging) {
                        int height = Math.max(notesCollapsedH(), Math.min(notesFullH(),
                                notesSheetStartHeight - Math.round(dy)));
                        applyNotesSheetHeight(height);
                    }
                    return true;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    float velocity = 0f;
                    if (notesSheetVelocity != null) {
                        notesSheetVelocity.addMovement(event);
                        notesSheetVelocity.computeCurrentVelocity(1000);
                        velocity = notesSheetVelocity.getYVelocity();
                        notesSheetVelocity.recycle();
                        notesSheetVelocity = null;
                    }
                    boolean dragged = notesSheetDragging;
                    notesSheetDragging = false;
                    if (!dragged && event.getActionMasked() == MotionEvent.ACTION_UP) {
                        view.performClick();
                    } else {
                        NotesSheet.State next = NotesSheet.snap(currentNotesSheetHeight(),
                                notesCollapsedH(), notesHalfH(), notesFullH(), velocity);
                        setNotesSheetState(next, true, -velocity);
                    }
                    return true;
                default:
                    return false;
            }
        };
    }

    private boolean notesVisible() {
        return NotesSheet.available(coverMode)
                && notesDock != null && notesDock.getVisibility() == View.VISIBLE;
    }

    private void wireNotesDrag(PaneViews article) {
        View.OnTouchListener listener = notesDragTouchListener(article.pane);
        View[] views = {article.card, article.kicker, article.heading, article.byline,
                article.state, article.speed, article.answer};
        for (View view : views) {
            if (view == null) continue;
            view.setOnTouchListener(listener);
        }
        if (article.heading != null) {
            article.heading.setAccessibilityDelegate(notesAccessibility(article));
        }
    }

    private View.OnTouchListener notesDragTouchListener(String pane) {
        return (view, event) -> {
            if (!NotesDrop.available(notesVisible())) return false;
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    cancelPendingNotesDrag();
                    notesDragDownX = event.getRawX();
                    notesDragDownY = event.getRawY();
                    pendingNotesDrag = () -> {
                        pendingNotesDrag = null;
                        if (NotesDrop.available(notesVisible())) startNotesDrag(pane, view);
                    };
                    handler.postDelayed(pendingNotesDrag, NotesDrop.LONG_PRESS_MS);
                    return false;
                case MotionEvent.ACTION_MOVE:
                    if (pendingNotesDrag != null && NotesDrop.movedTooFar(
                            event.getRawX() - notesDragDownX,
                            event.getRawY() - notesDragDownY,
                            ViewConfiguration.get(this).getScaledTouchSlop())) {
                        cancelPendingNotesDrag();
                    }
                    return false;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    cancelPendingNotesDrag();
                    return false;
                default:
                    return false;
            }
        };
    }

    private void cancelPendingNotesDrag() {
        if (pendingNotesDrag != null) {
            handler.removeCallbacks(pendingNotesDrag);
            pendingNotesDrag = null;
        }
    }

    private void startNotesDrag(String pane, View origin) {
        PaneViews article = paneViews.get(pane);
        if (article == null || !NotesDrop.available(notesVisible())) return;
        origin.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);
        String block = noteFromArticle(article);
        ClipData clip = ClipData.newPlainText(NotesDrop.ACTION_LABEL, block);
        notesDragActive = true;
        suppressArticleClick = pane;
        origin.startDragAndDrop(clip, notesDragShadow(article.card), block, 0);
    }

    private View.DragShadowBuilder notesDragShadow(View card) {
        // An answer card grows with its text. Draw only a bounded preview of its top section.
        int width = NotesDragShadowBounds.pixels(card.getWidth(),
                dp(NotesDragShadowBounds.MAX_WIDTH_DP));
        int height = NotesDragShadowBounds.pixels(card.getHeight(),
                dp(NotesDragShadowBounds.MAX_HEIGHT_DP));
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        card.draw(canvas);
        GradientDrawable frame = new GradientDrawable();
        frame.setColor(Color.TRANSPARENT);
        frame.setStroke(Math.max(2, dp(2)), themeColor(R.color.newspaper_ink));
        frame.setBounds(0, 0, width, height);
        frame.draw(canvas);
        return new View.DragShadowBuilder(card) {
            @Override public void onProvideShadowMetrics(Point size, Point touch) {
                size.set(width, height);
                touch.set(width / 2, Math.min(dp(24), height / 2));
            }
            @Override public void onDrawShadow(Canvas shadow) {
                shadow.drawBitmap(bitmap, 0, 0, null);
            }
        };
    }

    private View.OnDragListener notesTargetListener() {
        return (view, event) -> {
            switch (event.getAction()) {
                case DragEvent.ACTION_DRAG_STARTED:
                    boolean accept = NotesDrop.available(notesVisible())
                            && event.getClipDescription() != null
                            && event.getClipDescription().hasMimeType(ClipDescription.MIMETYPE_TEXT_PLAIN);
                    if (accept) highlightNotesTarget(true);
                    return accept;
                case DragEvent.ACTION_DRAG_ENTERED:
                    highlightNotesTarget(true);
                    return true;
                case DragEvent.ACTION_DRAG_LOCATION:
                    return true;
                case DragEvent.ACTION_DRAG_EXITED:
                    highlightNotesTarget(false);
                    return true;
                case DragEvent.ACTION_DROP:
                    highlightNotesTarget(false);
                    CharSequence text = event.getClipData() != null && event.getClipData().getItemCount() > 0
                            ? event.getClipData().getItemAt(0).getText() : null;
                    if (text != null) appendToNotes(text.toString());
                    notesDragActive = false;
                    return true;
                case DragEvent.ACTION_DRAG_ENDED:
                    highlightNotesTarget(false);
                    notesDragActive = false;
                    return true;
                default:
                    return false;
            }
        };
    }

    private void highlightNotesTarget(boolean on) {
        if (notesTab != null) notesTab.setBackground(landscapeLayout
                ? (on ? panelDrawable(palette.ink()) : null) : folderTabDrawable(on));
        if (notesCard != null) {
            notesCard.setBackground(panelDrawable(on ? palette.ink() : palette.stroke()));
        }
    }

    private void appendToNotes(String addition) {
        if (notes == null) return;
        String next = NotesDrop.append(notes.getText().toString(), addition);
        notes.setText(next);
        notes.setSelection(next.length());
        applyNotesCompact();
        showNotesConfirmation();
        if (notesSheetState == NotesSheet.State.COLLAPSED) {
            setNotesSheetState(NotesSheet.State.HALF, true);
        }
    }

    private void saveCardToNotes(String pane) {
        PaneViews article = paneViews.get(pane);
        if (article == null || !NotesDrop.available(notesVisible())) return;
        appendToNotes(noteFromArticle(article));
    }

    private String noteFromArticle(PaneViews article) {
        String model = article.heading.getText().toString();
        String questionText = latestQuestion;
        JSONObject answer = snapshot == null ? null : answerOf(snapshot, article.pane);
        if (answer != null && !answer.optString("question").isEmpty()) {
            questionText = answer.optString("question");
        }
        String time = DateFormat.getDateTimeInstance(DateFormat.FULL, DateFormat.SHORT)
                .format(new Date());
        return NotesDrop.format(model, questionText, article.rawAnswer, time);
    }

    private View.AccessibilityDelegate notesAccessibility(PaneViews article) {
        return new View.AccessibilityDelegate() {
            @Override public void onInitializeAccessibilityNodeInfo(View host,
                    AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(Button.class.getName());
                String description = getString(R.string.open_answer_description,
                        AnswerActionLabel.target(article.heading == null
                                ? null : article.heading.getText()));
                if (WorkingIndicator.working(article.state.getText())) {
                    // The count is read on demand; no per-word accessibility event is sent.
                    description += ", " + WorkingIndicator.spoken(article.state.getText(),
                            article.words);
                }
                info.setContentDescription(description);
                if (NotesDrop.available(notesVisible())) {
                    info.addAction(new AccessibilityNodeInfo.AccessibilityAction(
                            AccessibilityNodeInfo.ACTION_LONG_CLICK,
                            getString(R.string.save_to_notes)));
                }
            }

            @Override public boolean performAccessibilityAction(View host, int action, Bundle args) {
                if (NotesDrop.available(notesVisible())
                        && action == AccessibilityNodeInfo.ACTION_LONG_CLICK) {
                    saveCardToNotes(article.pane);
                    return true;
                }
                return super.performAccessibilityAction(host, action, args);
            }
        };
    }
}
