from app.application.dependencies import ResourceDependencies
def get_setting(key, dependencies, default=None):
    return dependencies.uow.settings.get(key, default)


def set_setting(key, value, dependencies: ResourceDependencies):
    return dependencies.uow.settings.set(key, value)


def consolidate_memory(days_passed, dependencies: ResourceDependencies):
    stats = dependencies.graph.consolidate_memory(days_passed=days_passed)
    return {"message": f"Memory consolidation finished (decayed {days_passed} days)", "stats": stats}
