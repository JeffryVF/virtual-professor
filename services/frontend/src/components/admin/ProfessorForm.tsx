'use client'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { createProfessor, updateProfessor, type Professor, type ProfessorCreate } from '@/lib/api'
import { Plus, Pencil } from 'lucide-react'

interface Props {
  professor?: Professor
  onSaved: (p: Professor) => void
}

const empty: ProfessorCreate = {
  name: '',
  topic: '',
  language: 'both',
  avatar_id: '',
  system_prompt: '',
}

export default function ProfessorForm({ professor, onSaved }: Props) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<ProfessorCreate>(professor ?? empty)
  const [saving, setSaving] = useState(false)

  const set = (k: keyof ProfessorCreate, v: string) => setForm(f => ({ ...f, [k]: v }))

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const saved = professor
        ? await updateProfessor(professor.id, form)
        : await createProfessor(form)
      toast.success(professor ? 'Professor updated' : 'Professor created')
      onSaved(saved)
      setOpen(false)
      if (!professor) setForm(empty)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {professor ? (
          <Button variant="ghost" size="icon"><Pencil className="h-4 w-4" /></Button>
        ) : (
          <Button><Plus className="h-4 w-4 mr-1" />New Professor</Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{professor ? 'Edit Professor' : 'New Professor'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 mt-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={form.name} onChange={e => set('name', e.target.value)} placeholder="Prof. García" required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="topic">Topic</Label>
              <Input id="topic" value={form.topic} onChange={e => set('topic', e.target.value)} placeholder="Calculus" required />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Language</Label>
              <Select value={form.language} onValueChange={v => set('language', v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="es">Spanish</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="both">Both</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="avatar_id">Avatar ID</Label>
              <Input
                id="avatar_id"
                value={form.avatar_id}
                onChange={e => set('avatar_id', e.target.value)}
                placeholder="e.g. dd73ea75-1218-4ef3-92ce-606d5f7fbc0a"
                required
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="system_prompt">System Prompt</Label>
            <Textarea
              id="system_prompt"
              value={form.system_prompt}
              onChange={e => set('system_prompt', e.target.value)}
              placeholder="You are a friendly professor specializing in…"
              rows={4}
              required
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
