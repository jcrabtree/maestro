import docker
import os, sys, time, subprocess, yaml, shutil
import logging
import dockermix

class ContainerMix:
  def __init__(self, conf_file=None, environment=None):
    self._setupLogging()
    self.containers = {}
    
    if environment:
      self.load(environment)
    else:
      if not conf_file.startswith('/'):
        conf_file = os.path.join(os.path.dirname(sys.argv[0]), conf_file)

      data = open(conf_file, 'r')
      self.config = yaml.load(data)      

  def get(self, container):
    return self.containers[container]

  def build(self):
    for container in self.config['containers']:
      base = self.config['containers'][container]['base']
      ports = None
      if 'ports' in self.config['containers'][container]:
        ports = self.config['containers'][container]['ports']
        
      self.log.info('Building container: %s using base template %s', container, base)
      build = Container(container, base_image=base, ports=ports)

      dockerfile = None
      if 'dockerfile' in self.config['containers'][container]:
        dockerfile = self.config['containers'][container]['dockerfile']
      build.build(dockerfile)

      self.containers[container] = build
      
  def destroy(self):
    for container in self.containers:
      self.log.info('Destroying container: %s', container)      
      self.containers[container].destroy()     
 
  def load(self, filename='envrionment.yml'):
    self.log.info('Loading environment from: %s', filename)      
    
    with open(filename, 'r') as input_file:
      environment = yaml.load(input_file)

      for container in environment['containers']:
        self.containers[container] = Container(container, build_tag=environment['containers'][container]['build_tag'], 
          container_id=environment['containers'][container]['container_id'], image_id=environment['containers'][container]['image_id'])
    
  def save(self, filename='environment.yml'):
    self.log.info('Saving environment state to: %s', filename)      
      
    with open(filename, 'w') as output_file:
      output_file.write(self.dump())

  def dump(self):
    result = {}
    result['containers'] = {}
    for container in self.containers:
      origin = self.containers[container]
      output = result['containers'][container] = {}
      output['image_id'] = str(origin.image_id)
      output['container_id'] = str(origin.container_id)
      output['build_tag'] = str(origin.build_tag)
      
      if origin.ports:
        output['ports'] = {}
        for port in origin.ports:
          public_port = origin.docker_client.port(origin.container_id, str(port))
          output['ports'][port] = str(public_port)

      str(self.containers[container].container_id)

    # TODO, change the YAML Dumper used here to be safe
    return yaml.dump(result)

  def _setupLogging(self):
    self.log = logging.getLogger('dockermix')
    self.log.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s %(levelname)-10s %(message)s")
    filehandler = logging.FileHandler('dockermix.log', 'w')
    filehandler.setLevel(logging.DEBUG)
    filehandler.setFormatter(formatter)
    self.log.addHandler(filehandler)
  

class Container:
  def __init__(self, name, command='/bin/true', build_tag=None, container_id=None, image_id=None, base_image=None, ports=None):
    self.log = logging.getLogger('dockermix')

    self.name = name
    self.command = command
    self.container_id=container_id
    self.image_id=image_id
    self.build_tag = build_tag
    if not build_tag:
      self.build_tag = name + '-' + str(os.getpid())
    
    self.docker_client = docker.Client()
    self.ports = ports
    self.base_image = 'ubuntu'
    if base_image:
      self.base_image = base_image

  def build(self, dockerfile=None):
    if dockerfile:        
      self._build_container(dockerfile)
    else:
      # If there's no dockerfile then we're just launching an empty base    
      self.image_id = self.base_image

    self._start_container()
    
  def destroy(self):
    self.docker_client.stop(self.container_id)
    self.docker_client.remove_container(self.container_id)    
    self.docker_client.remove_image(self.build_tag)

  def _build_container(self, dockerfile):
    # Build the container
    result = self.docker_client.build(dockerfile.split('\n'))
    self.image_id = result[0]
    
    # Tag the container with the name and process id
    self.docker_client.tag(self.image_id, self.build_tag)
    self.log.info('Container registered with tag: %s', self.build_tag)      

  def _start_container(self):
    # Start the container
    self.container_id = self.docker_client.create_container(self.image_id, self.command, 
      detach=True, ports=self.ports, hostname=self.build_tag)['Id']
    self.docker_client.start(self.container_id)

    self.log.info('Container started: %s', self.build_tag)      
      
class BaseContainer:
  def __init__(self, container_name):
    self.log = logging.getLogger('dockermix')
    self.log.info('Building base container: %s - This may take a while', container_name)      
    
    template = os.path.join(os.path.dirname(dockermix.__file__), 'docker', container_name + '.docker')
    self.dockerfile = open(template, 'r').readlines()
    self.docker_client = docker.Client()
    self.container_name = container_name
    
    self.build()

  def build(self):
    # Build the container
    result = self.docker_client.build(self.dockerfile)
    self.image_id = result[0]

    # Tag the container with the name
    self.docker_client.tag(self.image_id, self.container_name)
    self.log.info('Base container registered with tag: %s', self.container_name)      

  def destroy(self):
    self.log.info('Cleaning up base container: %s', self.container_name)      
    self.docker_client.remove_image(self.container_name)
