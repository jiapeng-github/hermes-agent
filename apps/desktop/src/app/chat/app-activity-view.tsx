import { useQuery } from '@tanstack/react-query'
import { AppWindow, ExternalLink, FileText, RefreshCw, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/error-state'
import { getAppActivitySession, launchAppActivityArtifact } from '@/hermes'
import { launchAppInBrowser } from '@/lib/app-launch'
import { cn } from '@/lib/utils'

interface AppActivityViewProps {
  profile?: string | null
  sessionId: string
}

const dateTime = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short'
})

export function AppActivityView({ profile, sessionId }: AppActivityViewProps) {
  const query = useQuery({
    queryKey: ['app-activity', profile || 'default', sessionId],
    queryFn: () => getAppActivitySession(sessionId, profile),
    refetchInterval: 5_000
  })

  const openArtifact = async (artifactId: string) => {
    const launch = await launchAppActivityArtifact(artifactId, profile)
    await window.hermesDesktop.apps.openLaunchUrl(launch.url)
  }

  if (query.isLoading) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center">
        <RefreshCw className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (query.isError || !query.data) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center px-8 py-10">
        <ErrorState description="应用活动记录暂时无法读取，请稍后重试。" title="加载失败">
          <Button onClick={() => void query.refetch()} size="sm" variant="outline">
            <RefreshCw className="size-4" />
            重试
          </Button>
        </ErrorState>
      </div>
    )
  }

  const { artifacts, session } = query.data

  return (
    <main className="relative min-h-0 flex-1 overflow-y-auto" data-testid="app-activity-view">
      <div className="mx-auto w-full max-w-4xl px-6 pb-16 pt-7">
        <div className="mb-6 flex items-start justify-between gap-5 border-b pb-5">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-primary">
              <AppWindow className="size-4" />
              应用活动会话
            </div>
            <h1 className="truncate text-xl font-semibold text-foreground">{session.app_name}</h1>
            <p className="mt-1 text-sm text-muted-foreground">每次主动生成的结果都会保存为可追溯的 HTML 产物。</p>
          </div>
          <Button onClick={() => void query.refetch()} size="icon" title="刷新活动记录" variant="outline">
            <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
          </Button>
        </div>

        {artifacts.length === 0 ? (
          <div className="grid min-h-72 place-items-center border border-dashed bg-(--ui-card-surface-background) px-8 text-center">
            <div>
              <FileText className="mx-auto mb-3 size-7 text-muted-foreground" />
              <h2 className="text-sm font-medium">还没有应用产物</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                在应用中完成一次搜索、刷新或分析后，结果会出现在这里。
              </p>
            </div>
          </div>
        ) : (
          <ol className="relative space-y-3 border-l pl-5">
            {artifacts.map(artifact => (
              <li className="relative" key={artifact.id}>
                <span className="absolute -left-[1.48rem] top-5 size-2.5 rounded-full border-2 border-background bg-primary" />
                <article className="border bg-(--ui-card-surface-background) p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h2 className="truncate text-sm font-semibold text-foreground">{artifact.title}</h2>
                      <time className="mt-1 block text-xs text-muted-foreground">
                        {dateTime.format(new Date(artifact.created_at * 1000))}
                      </time>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {Math.max(1, Math.round(artifact.size_bytes / 1024))} KB
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{artifact.summary}</p>
                  <div className="mt-4 flex flex-wrap justify-end gap-2 border-t pt-3">
                    <Button onClick={() => void launchAppInBrowser(artifact.app_id, profile)} size="sm" variant="ghost">
                      <Sparkles className="size-4" />
                      继续分析
                    </Button>
                    <Button onClick={() => void openArtifact(artifact.id)} size="sm" variant="outline">
                      <ExternalLink className="size-4" />
                      打开产物
                    </Button>
                  </div>
                </article>
              </li>
            ))}
          </ol>
        )}
      </div>
    </main>
  )
}
