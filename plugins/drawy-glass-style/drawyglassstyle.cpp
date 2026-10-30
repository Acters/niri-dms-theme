// SPDX-License-Identifier: MIT
#include <QApplication>
#include <QLayout>
#include <QProxyStyle>
#include <QStyleFactory>
#include <QStylePlugin>
#include <QToolButton>
#include <QVersionNumber>
#include <QWidget>

class DrawyGlassStyle final : public QProxyStyle {
public:
    explicit DrawyGlassStyle(QStyle *base) : QProxyStyle(base) {
        setObjectName(QStringLiteral("DrawyGlass"));
    }
    using QProxyStyle::polish;
    void polish(QWidget *widget) override {
        QProxyStyle::polish(widget);
        auto *button=qobject_cast<QToolButton *>(widget);
        auto *parent=widget->parentWidget();
        // Drawy 1.0.2 leaves this unconnected, unmanaged button underneath its zoom frame.
        if(button && parent && parent->inherits("BottomLeftWidgets")
            && QVersionNumber::fromString(qApp->applicationVersion())==QVersionNumber(1,0,2)
            && button->icon().name()==QStringLiteral("application-menu")
            && !button->defaultAction() && !button->menu()
            && parent->layout() && parent->layout()->indexOf(button)<0) {
            button->hide();
        }
    }
    int pixelMetric(PixelMetric metric,const QStyleOption *option=nullptr,const QWidget *widget=nullptr) const override {
        // Drawy's Frame uses this metric as its painted corner radius, not padding.
        if(metric==PM_ToolBarItemMargin && widget && widget->inherits("Frame")) return 16;
        return QProxyStyle::pixelMetric(metric,option,widget);
    }
};

class DrawyGlassStylePlugin final : public QStylePlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QStyleFactoryInterface_iid FILE "drawyglassstyle.json")
public:
    QStyle *create(const QString &key) override {
        if(key.compare(QStringLiteral("DrawyGlass"),Qt::CaseInsensitive)!=0) return nullptr;
        auto *base=QStyleFactory::create(QStringLiteral("Darkly"));
        return base ? new DrawyGlassStyle(base) : nullptr;
    }
};
#include "drawyglassstyle.moc"
