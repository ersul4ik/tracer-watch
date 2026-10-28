import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { REPO, getToken, setToken } from '@/lib/api'

const NEW_TOKEN = 'https://github.com/settings/personal-access-tokens/new'

/** The GitHub token used to send notes: stored only in this browser. */
export function Settings({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [value, setValue] = useState(getToken)
  const saved = Boolean(getToken())
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Метки с сайта</DialogTitle>
          <DialogDescription>
            Сайт отдаёт метку боту через GitHub. Для этого нужен токен, который умеет только запускать бота и не может
            менять код.
          </DialogDescription>
        </DialogHeader>
        <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm">
          <li>
            Открой{' '}
            <a className="text-primary underline" href={NEW_TOKEN} target="_blank" rel="noreferrer">
              создание токена на GitHub
            </a>
            .
          </li>
          <li>Repository access: Only select repositories → {REPO.split('/')[1]}.</li>
          <li>Permissions → Repository permissions → Actions: Read and write.</li>
          <li>Expiration: самый долгий срок. Сгенерируй токен и вставь его сюда.</li>
        </ol>
        <Input
          id="github-token"
          type="password"
          autoComplete="off"
          placeholder="github_pat_…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Токен хранится только в этом браузере. На другом устройстве его нужно вставить ещё раз.
        </p>
        <DialogFooter>
          {saved && (
            <Button
              variant="ghost"
              onClick={() => {
                setToken('')
                setValue('')
              }}
            >
              Забыть токен
            </Button>
          )}
          <Button
            onClick={() => {
              setToken(value)
              onOpenChange(false)
            }}
            disabled={!value.trim()}
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
