import os

from distutils.dir_util import mkpath
from collections import OrderedDict

import yaml

from jinja2 import Environment, PackageLoader
env = Environment(loader=PackageLoader('hokusai', 'templates'))

from hokusai.command import command
from hokusai.config import config
from hokusai.common import print_green, build_service, build_deployment, YAML_HEADER

@command
def setup(project_name, aws_account_id, aws_ecr_region, framework, port,
          with_memcached, with_redis, with_mongodb, with_postgres, with_rabbitmq):

  mkpath(os.path.join(os.getcwd(), 'hokusai'))

  config.create(project_name.lower().replace('_', '-'), aws_account_id, aws_ecr_region)

  if framework == 'rack':
    dockerfile = env.get_template("Dockerfile-ruby.j2")
    base_image = 'ruby:latest'
    run_command = 'bundle exec rackup'
    development_command = 'bundle exec rackup'
    test_command = 'bundle exec rake'
    runtime_environment = {
      'development': ["RACK_ENV=development"],
      'test': ["RACK_ENV=test"],
      'staging': [{'name': 'RACK_ENV', 'value': 'staging'}],
      'production': [{'name': 'RACK_ENV', 'value': 'production'}]
    }

  elif framework == 'nodejs':
    dockerfile = env.get_template("Dockerfile-node.j2")
    base_image = 'node:latest'
    run_command = 'node index.js'
    development_command = 'node index.js'
    test_command = 'npm test'
    runtime_environment = {
      'development': ["NODE_ENV=development"],
      'test': ["NODE_ENV=test"],
      'staging': [{'name': 'NODE_ENV', 'value': 'staging'}],
      'production': [{'name': 'NODE_ENV', 'value': 'production'}]
    }

  elif framework == 'elixir':
    dockerfile = env.get_template("Dockerfile-elixir.j2")
    base_image = 'elixir:latest'
    run_command = 'mix run --no-halt'
    development_command = 'mix run'
    test_command = 'mix test'
    runtime_environment = {
      'development': ["MIX_ENV=dev"],
      'test': ["MIX_ENV=test"],
      'staging': [{'name': 'MIX_ENV', 'value': 'prod'}],
      'production': [{'name': 'MIX_ENV', 'value': 'prod'}]
    }

  with open(os.path.join(os.getcwd(), 'Dockerfile'), 'w') as f:
    f.write(dockerfile.render(base_image=base_image, command=run_command, target_port=port))

  with open(os.path.join(os.getcwd(), 'hokusai', "common.yml"), 'w') as f:
    services = {
      config.project_name: {
        'build': {
          'context': '../'
        }
      }
    }
    data = OrderedDict([
        ('version', '2'),
        ('services', services)
      ])
    payload = YAML_HEADER + yaml.safe_dump(data, default_flow_style=False)
    f.write(payload)

  for idx, compose_environment in enumerate(['development', 'test']):
    with open(os.path.join(os.getcwd(), 'hokusai', "%s.yml" % compose_environment), 'w') as f:
      services = {
        config.project_name: {
          'extends': {
            'file': 'common.yml',
            'service': config.project_name
          }
        }
      }

      if compose_environment == 'development':
        services[config.project_name]['command'] = development_command
        services[config.project_name]['ports'] = ["%s:%s" % (port, port)]
      if compose_environment == 'test':
        services[config.project_name]['command'] = test_command

      services[config.project_name]['environment'] = runtime_environment[compose_environment]

      if with_memcached or with_redis or with_mongodb or with_postgres or with_rabbitmq:
        services[config.project_name]['depends_on'] = []

      if with_memcached:
        services["%s-memcached" % config.project_name] = {
          'image': 'memcached'
        }
        if compose_environment == 'development':
          services["%s-memcached" % config.project_name]['ports'] = ["11211:11211"]
        services[config.project_name]['environment'].append("MEMCACHED_SERVERS=%s-memcached:11211" % config.project_name)
        services[config.project_name]['depends_on'].append("%s-memcached" % config.project_name)

      if with_redis:
        services["%s-redis" % config.project_name] = {
          'image': 'redis:3.2-alpine'
        }
        if compose_environment == 'development':
          services["%s-redis" % config.project_name]['ports'] = ["6379:6379"]
        services[config.project_name]['environment'].append("REDIS_URL=redis://%s-redis:6379/%d" % (config.project_name, idx))
        services[config.project_name]['depends_on'].append("%s-redis" % config.project_name)

      if with_mongodb:
        services["%s-mongodb" % config.project_name] = {
          'image': 'mongo:3.0',
          'command': 'mongod --smallfiles'
        }
        if compose_environment == 'development':
          services["%s-mongodb" % config.project_name]['ports'] = ["27017:27017"]
        services[config.project_name]['environment'].append("MONGO_URL=mongodb://%s-mongodb:27017/%s" % (config.project_name, compose_environment))
        services[config.project_name]['depends_on'].append("%s-mongodb" % config.project_name)

      if with_postgres:
        services["%s-postgres" % config.project_name] = {
          'image': 'postgres:9.4'
        }
        if compose_environment == 'development':
          services["%s-postgres" % config.project_name]['ports'] = ["5432:5432"]
        services[config.project_name]['environment'].append("DATABASE_URL=postgresql://%s-postgres/%s" % (config.project_name, compose_environment))
        services[config.project_name]['depends_on'].append("%s-postgres" % config.project_name)

      if with_rabbitmq:
        services["%s-rabbitmq" % config.project_name] = {
          'image': 'rabbitmq:3.6-management'
        }
        if compose_environment == 'development':
          services["%s-rabbitmq" % config.project_name]['ports'] = ["5672:5672","15672:15672"]
        services[config.project_name]['environment'].append("RABBITMQ_URL=amqp://%s-rabbitmq/%s" % (config.project_name, compose_environment))
        services[config.project_name]['depends_on'].append("%s-rabbitmq" % config.project_name)

      data = OrderedDict([
        ('version', '2'),
        ('services', services)
      ])
      payload = YAML_HEADER + yaml.safe_dump(data, default_flow_style=False)
      f.write(payload)

  for stack in ['staging', 'production']:
    with open(os.path.join(os.getcwd(), 'hokusai', "%s.yml" % stack), 'w') as f:
      environment = runtime_environment[stack]

      if with_memcached:
        environment.append({'name': 'MEMCACHED_SERVERS', 'valueFrom': {'secretKeyRef': { 'name': "%s-secrets" % config.project_name, 'key': 'MEMCACHED_SERVERS'}}})
      if with_redis:
        environment.append({'name': 'REDIS_URL', 'valueFrom': {'secretKeyRef': { 'name': "%s-secrets" % config.project_name, 'key': 'REDIS_URL'}}})
      if with_mongodb:
        environment.append({'name': 'MONGO_URL', 'valueFrom': {'secretKeyRef': { 'name': "%s-secrets" % config.project_name, 'key': 'MONGO_URL'}}})
      if with_postgres:
        environment.append({'name': 'DATABASE_URL', 'valueFrom': {'secretKeyRef': { 'name': "%s-secrets" % config.project_name, 'key': 'DATABASE_URL'}}})
      if with_rabbitmq:
        environment.append({'name': 'RABBITMQ_URL', 'valueFrom': {'secretKeyRef': { 'name': "%s-secrets" % config.project_name, 'key': 'RABBITMQ_URL'}}})

      deployment_data = build_deployment(config.project_name,
                                          "%s:%s" % (config.aws_ecr_registry, stack),
                                          port, environment=environment, always_pull=True)

      service_data = build_service(config.project_name, port, target_port=port, internal=False)

      stack_yaml = deployment_data + service_data

      if with_memcached:
        stack_yaml += build_deployment("%s-memcached" % config.project_name, 'memcached', 11211)
        stack_yaml += build_service("%s-memcached" % config.project_name, 11211)

      if with_redis:
        stack_yaml += build_deployment("%s-redis" % config.project_name, 'redis:3.2-alpine', 6379)
        stack_yaml += build_service("%s-redis" % config.project_name, 6379)

      if with_mongodb:
        stack_yaml += build_deployment("%s-mongodb" % config.project_name, 'mongodb:3.0', 27017)
        stack_yaml += build_service("%s-mongodb" % config.project_name, 27017)

      if with_postgres:
        stack_yaml += build_deployment("%s-postgres" % config.project_name, 'postgres:9.4', 5432)
        stack_yaml += build_service("%s-postgres" % config.project_name, 5432)

      if with_rabbitmq:
        stack_yaml += build_deployment("%s-rabbitmq" % config.project_name, 'rabbitmq:3.6-management', 5672)
        stack_yaml += build_service("%s-rabbitmq" % config.project_name, 5672)

      f.write(stack_yaml)

  print_green("Config created in ./hokusai")
