// SPDX-License-Identifier: MIT
#include <KConfigGroup>
#include <KPluginFactory>
#include <KSharedConfig>
#include <KTextEditor/Editor>
#include <KTextEditor/MainWindow>
#include <KTextEditor/Plugin>
#include <KTextEditor/View>
#include <KSyntaxHighlighting/Repository>
#include <KSyntaxHighlighting/Theme>

#include <QApplication>
#include <QLoggingCategory>
#include <QPalette>
#include <QTimer>
#include <QStringList>

Q_LOGGING_CATEGORY(balancedGlassLog, "kate.balancedglass", QtWarningMsg)

// The host owns one helper for each main window, including its connections and
// queued work. There are no stored view pointers and no global renderer writes.
class BalancedGlassWindow final : public QObject
{
public:
    explicit BalancedGlassWindow(KTextEditor::MainWindow *window)
        : QObject(window)
        , m_window(window)
        , m_config(KSharedConfig::openConfig(QStringLiteral("katebalancedglassrc"), KConfig::NoGlobals))
    {
        m_syncTimer.setSingleShot(true);
        m_syncTimer.setInterval(0);
        connect(&m_syncTimer, &QTimer::timeout, this, [this] { sync(); });

        auto *editor = KTextEditor::Editor::instance();
        connect(editor, &KTextEditor::Editor::configChanged, this, [this] { scheduleSync(); });
        connect(editor, &KTextEditor::Editor::repositoryReloaded, this, [this] { scheduleSync(); });
        connect(window, &KTextEditor::MainWindow::viewCreated, this, [this] { scheduleSync(); });
        scheduleSync();
    }

private:
    void scheduleSync()
    {
        if (!m_syncTimer.isActive()) {
            m_syncTimer.start();
        }
    }

    void sync()
    {
        // Read only; allowing edits to this optional file requires no watcher,
        // but they take effect at the next normal synchronization trigger.
        m_config->reparseConfiguration();
        const KConfigGroup themes(m_config, QStringLiteral("Themes"));
        const bool dark = qApp->palette().color(QPalette::Base).lightness() < 128;
        const QString name = dark
            ? themes.readEntry("Dark", QStringLiteral("Balanced Glass Dark"))
            : themes.readEntry("Light", QStringLiteral("Balanced Glass Light"));

        auto *editor = KTextEditor::Editor::instance();
        if (!editor->repository().theme(name).isValid()) {
            // Do not pass an unknown/empty name: KTextEditor silently substitutes
            // a palette-matched theme and would still make that choice local.
            if (m_lastMissingTheme != name || !m_warnedMissingTheme) {
                qCWarning(balancedGlassLog) << "Theme not found; leaving views unchanged:" << name;
                m_lastMissingTheme = name;
                m_warnedMissingTheme = true;
            }
            return;
        }
        m_warnedMissingTheme = false;

        for (auto *view : m_window->views()) {
            if (view->configValue(QStringLiteral("theme")).toString() != name) {
                qCDebug(balancedGlassLog) << "Setting view" << view << "theme to" << name;
                view->setConfigValue(QStringLiteral("theme"), name);
            }
        }
    }

    KTextEditor::MainWindow *const m_window;
    KSharedConfig::Ptr m_config;
    QTimer m_syncTimer;
    QString m_lastMissingTheme;
    bool m_warnedMissingTheme = false;
};

class BalancedGlassPlugin final : public KTextEditor::Plugin
{
    Q_OBJECT
public:
    explicit BalancedGlassPlugin(QObject *parent)
        : KTextEditor::Plugin(parent)
    {
    }

    QObject *createView(KTextEditor::MainWindow *window) override
    {
        const auto desktops = qEnvironmentVariable("XDG_CURRENT_DESKTOP").split(QLatin1Char(':'), Qt::SkipEmptyParts);
        if (qEnvironmentVariable("NIRI_DMS_THEME_PROFILE") != QLatin1String("niri-dms-glass")
            || !desktops.contains(QStringLiteral("niri"), Qt::CaseInsensitive)) {
            return new QObject(window);
        }
        return new BalancedGlassWindow(window);
    }
};

K_PLUGIN_FACTORY_WITH_JSON(BalancedGlassPluginFactory, "balancedglassplugin.json", registerPlugin<BalancedGlassPlugin>();)

#include "balancedglassplugin.moc"
