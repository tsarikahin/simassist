from uuid import UUID, uuid4

import pytest

from simassist.projects.workspace import WorkspaceRepository


def test_independent_chats_and_delete(tmp_path):
    store = WorkspaceRepository(tmp_path / 'jobs.db')
    project = UUID(store.new_project()['id'])
    chat_a = UUID(store.new_chat(project)['id'])
    chat_b = UUID(store.new_chat(project)['id'])
    store.append(project, chat_a, 'user', 'Create an annulus')
    store.append(project, chat_a, 'assistant', 'Done')
    assert len(store.messages(project, chat_a)) == 2
    assert store.messages(project, chat_b) == []
    assert store.chats(project)[1]['title'] == 'Create an annulus'
    store.delete_chat(project, chat_a)
    assert len(store.chats(project)) == 1
    with pytest.raises(KeyError):
        store.messages(project, chat_a)


def test_cross_project_chat_access_forbidden(tmp_path):
    store = WorkspaceRepository(tmp_path / 'jobs.db')
    a = UUID(store.new_project('A')['id'])
    b = UUID(store.new_project('B')['id'])
    chat = UUID(store.new_chat(a)['id'])
    with pytest.raises(KeyError):
        store.messages(b, chat)
    with pytest.raises(KeyError):
        store.delete_chat(b, chat)


def test_geometry_soft_delete_and_rename(tmp_path):
    store = WorkspaceRepository(tmp_path / 'jobs.db')
    project = UUID(store.new_project()['id'])
    job = uuid4()
    store.update_geometry(project, job, name='Annulus 2D')
    assert store.geometry_overrides(project)[str(job)]['display_name'] == 'Annulus 2D'
    store.update_geometry(project, job, deleted=True)
    assert store.geometry_overrides(project)[str(job)]['deleted'] == 1
    # A soft delete does not touch job or artifact tables.


def test_legacy_import_idempotent(tmp_path):
    store = WorkspaceRepository(tmp_path / 'jobs.db')
    assert store.import_legacy()['id'] == store.import_legacy()['id']
    assert len(store.projects()) == 1
