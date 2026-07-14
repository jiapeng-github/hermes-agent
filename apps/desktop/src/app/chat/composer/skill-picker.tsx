import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { HermesGateway } from '@/hermes'
import { useI18n } from '@/i18n'
import { type CommandsCatalogLike, isDesktopSlashExtensionCommand } from '@/lib/desktop-slash-commands'
import { ChevronDown, Loader2, Wrench } from '@/lib/icons'

export interface SkillCommandOption {
  command: string
  description: string
}

/**
 * The catalog intentionally lists skills only in its flat `pairs` response.
 * Categorized entries are built-in or user quick commands, so excluding them
 * leaves the skill-backed slash commands the picker should offer.
 */
export function skillOptionsFromCatalog(catalog: CommandsCatalogLike): SkillCommandOption[] {
  const categorized = new Set(
    (catalog.categories ?? []).flatMap(section => section.pairs.map(([command]) => command.trim().toLowerCase()))
  )

  const seen = new Set<string>()

  return (catalog.pairs ?? []).flatMap(([rawCommand, rawDescription]) => {
    const command = rawCommand.trim()
    const key = command.toLowerCase()

    if (!command || categorized.has(key) || seen.has(key) || !isDesktopSlashExtensionCommand(command)) {
      return []
    }

    seen.add(key)

    return [{ command, description: rawDescription.trim() }]
  })
}

export function SkillPicker({
  disabled,
  gateway,
  onPick
}: {
  disabled: boolean
  gateway: HermesGateway | null
  onPick: (command: string) => void
}) {
  const { t } = useI18n()
  const copy = t.composer
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [skills, setSkills] = useState<SkillCommandOption[]>([])
  const [loading, setLoading] = useState(false)
  const requestRef = useRef(0)

  useEffect(() => {
    if (!open || !gateway) {
      return
    }

    const requestId = ++requestRef.current

    setLoading(true)
    void gateway
      .request<CommandsCatalogLike>('commands.catalog')
      .then(catalog => {
        if (requestRef.current === requestId) {
          setSkills(skillOptionsFromCatalog(catalog))
        }
      })
      .catch(() => {
        if (requestRef.current === requestId) {
          setSkills([])
        }
      })
      .finally(() => {
        if (requestRef.current === requestId) {
          setLoading(false)
        }
      })
  }, [gateway, open])

  const searchableSkills = useMemo(
    () => skills.map(skill => ({ ...skill, searchValue: `${skill.command} ${skill.description}` })),
    [skills]
  )

  const pick = (command: string) => {
    onPick(command)
    setOpen(false)
    setSearch('')
  }

  return (
    <Popover
      onOpenChange={nextOpen => {
        setOpen(nextOpen)

        if (!nextOpen) {
          setSearch('')
        }
      }}
      open={open}
    >
      <PopoverTrigger asChild>
        <Button
          aria-label={copy.selectSkill}
          className="h-6 gap-1 rounded-md px-1.5 text-[0.7rem] font-medium text-muted-foreground hover:bg-accent/60 hover:text-foreground"
          disabled={disabled || !gateway}
          size="sm"
          type="button"
          variant="ghost"
        >
          <Wrench className="size-3" />
          <span>{copy.skills}</span>
          <ChevronDown className="size-3 opacity-70" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))] overflow-hidden p-0" side="top">
        <Command className="max-h-76 rounded-lg bg-transparent">
          <CommandInput autoFocus onValueChange={setSearch} placeholder={copy.searchSkills} value={search} />
          <CommandList className="max-h-64 p-1">
            {loading ? (
              <div className="flex items-center gap-2 px-2 py-3 text-sm text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                <span>{copy.loadingSkills}</span>
              </div>
            ) : (
              <>
                <CommandEmpty>{copy.noMatchingSkills}</CommandEmpty>
                {searchableSkills.map(skill => (
                  <CommandItem
                    key={skill.command}
                    onSelect={() => pick(skill.command)}
                    value={skill.searchValue}
                  >
                    <span className="grid size-5 shrink-0 place-items-center rounded bg-primary/10 text-primary">
                      <Wrench className="size-3" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-[0.75rem] font-medium">{skill.command}</span>
                      {skill.description && (
                        <span className="block truncate text-[0.7rem] text-muted-foreground">{skill.description}</span>
                      )}
                    </span>
                  </CommandItem>
                ))}
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
