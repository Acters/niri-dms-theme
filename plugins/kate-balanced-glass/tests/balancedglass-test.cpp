#include <QApplication>
#include <QMainWindow>
#include <QPalette>
#include <QTest>
#include <KPluginFactory>
#include <KPluginMetaData>
#include <KTextEditor/Document>
#include <KTextEditor/Editor>
#include <KTextEditor/MainWindow>
#include <KTextEditor/Plugin>
#include <KTextEditor/View>
#include <KSyntaxHighlighting/Theme>
#include <memory>

class Backend final : public QObject {
    Q_OBJECT
public:
    QMainWindow host;
    KTextEditor::MainWindow wrapper{this};
    QList<KTextEditor::View *> items;
    KTextEditor::View *addView(KTextEditor::Document *doc) {
        auto *view=doc->createView(&host,&wrapper);
        items.append(view);
        emit wrapper.viewCreated(view);
        return view;
    }
public Q_SLOTS:
    QList<KTextEditor::View *> views() { return items; }
    QWidget *window() { return &host; }
    QWidget *createViewBar(KTextEditor::View *) { return new QWidget(&host); }
    void deleteViewBar(KTextEditor::View *) {}
    void addWidgetToViewBar(KTextEditor::View *, QWidget *widget) { widget->setParent(&host); }
    void showViewBar(KTextEditor::View *) {}
    void hideViewBar(KTextEditor::View *) {}
    KTextEditor::View *activeView() { return items.isEmpty() ? nullptr : items.last(); }
};

class BalancedGlassTest final : public QObject {
    Q_OBJECT
    void setDark(bool dark) {
        auto p=qApp->palette();
        p.setColor(QPalette::Base,QColor(dark ? "#000000" : "#f7f9ff"));
        p.setColor(QPalette::Window,QColor(dark ? "#000000" : "#f7f9ff"));
        p.setColor(QPalette::Text,QColor(dark ? "#e0e2e8" : "#181c20"));
        qApp->setPalette(p);
    }
    static QString theme(KTextEditor::View *view) { return view->configValue(QStringLiteral("theme")).toString(); }
private Q_SLOTS:
    void switchesExistingSplitNewAndMultipleWindowViews() {
        qputenv("NIRI_DMS_THEME_PROFILE", "niri-dms-glass");
        qputenv("XDG_CURRENT_DESKTOP", "niri");
        setDark(false);
        auto *editor=KTextEditor::Editor::instance();
        Backend a;
        std::unique_ptr<KTextEditor::Document> doc(editor->createDocument(this));
        QVERIFY(doc->setText(QStringLiteral("int main() { return 0; }\n")));
        auto *first=a.addView(doc.get());
        QVERIFY(!theme(first).startsWith(QStringLiteral("Balanced Glass")));

        const KPluginMetaData metadata(QString::fromLocal8Bit(qgetenv("BALANCED_GLASS_PLUGIN")));
        QVERIFY2(metadata.isValid(),qPrintable(metadata.fileName()));
        auto result=KPluginFactory::instantiatePlugin<KTextEditor::Plugin>(metadata,this);
        QVERIFY2(result.plugin,qPrintable(result.errorString));
        std::unique_ptr<KTextEditor::Plugin> plugin(result.plugin);
        std::unique_ptr<QObject> controllerA(plugin->createView(&a.wrapper));
        QTRY_COMPARE(theme(first),QStringLiteral("Balanced Glass Light"));
        QCOMPARE(QColor::fromRgba(first->theme().editorColor(KSyntaxHighlighting::Theme::BackgroundColor)).alpha(),102);
        QCOMPARE(QColor::fromRgba(first->theme().editorColor(KSyntaxHighlighting::Theme::IconBorder)).alpha(),163);

        setDark(true);
        QTRY_COMPARE(theme(first),QStringLiteral("Balanced Glass Dark"));
        auto *split=a.addView(doc.get());
        // Simulate configuration applied later in the new-view lifecycle.
        split->setConfigValue(QStringLiteral("theme"),QStringLiteral("Breeze Light"));
        QTRY_COMPARE(theme(split),QStringLiteral("Balanced Glass Dark"));

        Backend b;
        auto *secondWindow=b.addView(doc.get());
        std::unique_ptr<QObject> controllerB(plugin->createView(&b.wrapper));
        QTRY_COMPARE(theme(secondWindow),QStringLiteral("Balanced Glass Dark"));
        setDark(false);
        for(auto *view:{first,split,secondWindow}) {
            QTRY_COMPARE(theme(view),QStringLiteral("Balanced Glass Light"));
            QCOMPARE(QColor::fromRgba(view->theme().editorColor(KSyntaxHighlighting::Theme::BackgroundColor)).alpha(),102);
        }
        setDark(true);
        for(auto *view:{first,split,secondWindow}) QTRY_COMPARE(theme(view),QStringLiteral("Balanced Glass Dark"));

        controllerA.reset(); controllerB.reset(); plugin.reset();
        auto *unmanaged=a.addView(doc.get());
        QCoreApplication::processEvents();
        QVERIFY(!theme(unmanaged).startsWith(QStringLiteral("Balanced Glass")));
        QCOMPARE(QColor::fromRgba(unmanaged->theme().editorColor(KSyntaxHighlighting::Theme::BackgroundColor)).alpha(),255);
        // Views are owned by the host; delete before the shared document.
        for(auto *view:a.items) delete view;
        a.items.clear();
        for(auto *view:b.items) delete view;
        b.items.clear();
        doc.reset();
    }
    void doesNotOverrideOtherDesktopOrUnmarkedSession() {
        const KPluginMetaData metadata(QString::fromLocal8Bit(qgetenv("BALANCED_GLASS_PLUGIN")));
        for (const auto &desktop : {QByteArray("COSMIC"), QByteArray("niri")}) {
            qputenv("XDG_CURRENT_DESKTOP", desktop);
            if (desktop == "COSMIC") qputenv("NIRI_DMS_THEME_PROFILE", "niri-dms-glass");
            else qunsetenv("NIRI_DMS_THEME_PROFILE");
            setDark(false);
            Backend backend;
            std::unique_ptr<KTextEditor::Document> doc(KTextEditor::Editor::instance()->createDocument(this));
            auto *view = backend.addView(doc.get());
            auto result = KPluginFactory::instantiatePlugin<KTextEditor::Plugin>(metadata, this);
            QVERIFY(result.plugin);
            std::unique_ptr<KTextEditor::Plugin> plugin(result.plugin);
            std::unique_ptr<QObject> controller(plugin->createView(&backend.wrapper));
            QCoreApplication::processEvents();
            QVERIFY(!theme(view).startsWith(QStringLiteral("Balanced Glass")));
            setDark(true);
            QCoreApplication::processEvents();
            QVERIFY(!theme(view).startsWith(QStringLiteral("Balanced Glass")));
            controller.reset(); plugin.reset();
            delete view; backend.items.clear(); doc.reset();
        }
    }
};
QTEST_MAIN(BalancedGlassTest)
#include "balancedglass-test.moc"
